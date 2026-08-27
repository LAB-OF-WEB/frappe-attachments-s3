# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe and Contributors
# See license.txt
from __future__ import unicode_literals

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock dependencies if not installed in standalone environment
for mod in [
    "frappe",
    "frappe.utils",
    "frappe.model",
    "frappe.model.document",
    "boto3",
    "botocore",
    "botocore.client",
    "botocore.exceptions",
    "magic",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

import frappe
from frappe_s3_attachment.controller import (
    update_all_matching_file_records,
    upload_existing_files_s3,
    file_upload_to_s3,
    process_files_migration,
    s3_file_regex_match,
)


class TestS3FileAttachment(unittest.TestCase):

    def setUp(self):
        frappe.reset_mock()
        frappe.utils.get_site_path = MagicMock(return_value="/sites/mysite")
        frappe.local.conf = {}

    @patch("frappe.db.commit")
    @patch("frappe.db.set_value")
    @patch("frappe.get_meta")
    @patch("frappe.db.sql")
    @patch("frappe.get_all")
    def test_update_all_matching_file_records_public(
        self, mock_get_all, mock_db_sql, mock_get_meta, mock_set_value, mock_commit
    ):
        mock_get_all.return_value = [
            {
                "name": "FILE-001",
                "file_name": "sample.pdf",
                "attached_to_doctype": "Sales Invoice",
                "attached_to_name": "ACC-SINV-2026-00001",
                "is_private": 0,
            },
            {
                "name": "FILE-002",
                "file_name": "sample.pdf",
                "attached_to_doctype": "Item",
                "attached_to_name": "ITEM-001",
                "is_private": 0,
            },
        ]
        mock_meta = MagicMock()
        mock_meta.get.side_effect = lambda k: "image" if k == "image_field" else None
        mock_get_meta.return_value = mock_meta

        mock_s3 = MagicMock()
        mock_s3.S3_CLIENT.meta.endpoint_url = "https://s3.amazonaws.com"
        mock_s3.BUCKET = "test-bucket"

        updated = update_all_matching_file_records(
            original_path="/files/sample.pdf",
            is_private=0,
            key="2026/08/22/Item/ABC_sample.pdf",
            s3_upload=mock_s3,
        )

        self.assertEqual(updated, ["FILE-001", "FILE-002"])
        self.assertEqual(mock_db_sql.call_count, 2)
        mock_commit.assert_called_once()
        self.assertEqual(mock_set_value.call_count, 2)

    @patch("frappe.db.commit")
    @patch("frappe.db.sql")
    @patch("frappe.get_all")
    def test_update_all_matching_file_records_private(
        self, mock_get_all, mock_db_sql, mock_commit
    ):
        mock_get_all.return_value = [
            {
                "name": "FILE-PRIV-001",
                "file_name": "payroll.pdf",
                "attached_to_doctype": None,
                "attached_to_name": None,
                "is_private": 1,
            }
        ]
        mock_s3 = MagicMock()
        mock_s3.BUCKET = "test-bucket"

        updated = update_all_matching_file_records(
            original_path="/private/files/payroll.pdf",
            is_private=1,
            key="2026/08/22/Salary/XYZ_payroll.pdf",
            s3_upload=mock_s3,
        )

        self.assertEqual(updated, ["FILE-PRIV-001"])
        mock_commit.assert_called_once()
        sql_call_args = mock_db_sql.call_args[0][1]
        self.assertIn("/api/method/frappe_s3_attachment.controller.generate_file", sql_call_args[0])
        self.assertIn("key=2026/08/22/Salary/XYZ_payroll.pdf", sql_call_args[0])

    @patch("os.remove")
    @patch("frappe_s3_attachment.controller.update_all_matching_file_records")
    @patch("frappe_s3_attachment.controller.S3Operations")
    @patch("os.path.exists", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.get_value", return_value="FILE-001")
    def test_upload_existing_files_s3_removes_file_after_update(
        self,
        mock_get_value,
        mock_get_doc,
        mock_exists,
        mock_s3_ops,
        mock_update_records,
        mock_os_remove,
    ):
        frappe.utils.get_site_path.return_value = "/sites/mysite"
        mock_doc = MagicMock()
        mock_doc.name = "FILE-001"
        mock_doc.file_url = "/files/test.png"
        mock_doc.file_name = "test.png"
        mock_doc.is_private = 0
        mock_doc.attached_to_doctype = "Item"
        mock_doc.attached_to_name = "ITEM-01"
        mock_get_doc.return_value = mock_doc

        s3_inst = MagicMock()
        s3_inst.upload_files_to_s3_with_key.return_value = "2026/08/22/Item/KEY_test.png"
        s3_inst.verify_s3_object_exists.return_value = True
        mock_s3_ops.return_value = s3_inst

        mock_update_records.return_value = ["FILE-001", "FILE-002"]

        result = upload_existing_files_s3("FILE-001")

        self.assertEqual(result, ["FILE-001", "FILE-002"])
        mock_update_records.assert_called_once_with(
            "/files/test.png", 0, "2026/08/22/Item/KEY_test.png", s3_inst
        )
        mock_os_remove.assert_called_once_with("/sites/mysite/public/files/test.png")

    @patch("os.remove")
    @patch("frappe_s3_attachment.controller.update_all_matching_file_records")
    @patch("frappe_s3_attachment.controller.S3Operations")
    @patch("os.path.exists", return_value=True)
    def test_file_upload_to_s3_live_upload(
        self, mock_exists, mock_s3_ops, mock_update_records, mock_os_remove
    ):
        frappe.utils.get_site_path.return_value = "/sites/mysite"
        doc = MagicMock()
        doc.name = "FILE-LIVE-001"
        doc.file_url = "/files/live.pdf"
        doc.file_name = "live.pdf"
        doc.is_private = 0
        doc.attached_to_doctype = "Customer"
        doc.attached_to_name = "CUST-001"

        s3_inst = MagicMock()
        s3_inst.upload_files_to_s3_with_key.return_value = "2026/08/22/Customer/KEY_live.pdf"
        s3_inst.verify_s3_object_exists.return_value = True
        s3_inst.S3_CLIENT.meta.endpoint_url = "https://s3.amazonaws.com"
        s3_inst.BUCKET = "test-bucket"
        mock_s3_ops.return_value = s3_inst

        file_upload_to_s3(doc, "after_insert")

        mock_update_records.assert_called_once_with(
            "/files/live.pdf", 0, "2026/08/22/Customer/KEY_live.pdf", s3_inst
        )
        mock_os_remove.assert_called_once_with("/sites/mysite/public/files/live.pdf")

    @patch("frappe.publish_realtime")
    @patch("frappe_s3_attachment.controller.upload_existing_files_s3")
    @patch("os.path.exists", return_value=True)
    @patch("frappe.get_all")
    def test_process_files_migration_deduplication(
        self, mock_get_all, mock_exists, mock_upload_existing, mock_publish
    ):
        frappe.utils.get_site_path.return_value = "/sites/mysite"
        # Simulate batching with 2 file records sharing the same physical file
        mock_get_all.side_effect = [
            [
                {"name": "FILE-001", "file_url": "/files/shared.pdf", "is_private": 0},
                {"name": "FILE-002", "file_url": "/files/shared.pdf", "is_private": 0},
            ],
            []
        ]
        # When FILE-001 is processed, upload_existing_files_s3 updates BOTH FILE-001 and FILE-002
        mock_upload_existing.return_value = ["FILE-001", "FILE-002"]

        process_files_migration(user="Administrator")

        # upload_existing_files_s3 should only be called ONCE for the shared file
        self.assertEqual(mock_upload_existing.call_count, 1)
        mock_publish.assert_called_once()

    def test_s3_file_regex_match(self):
        self.assertTrue(s3_file_regex_match("https://s3.amazonaws.com/bucket/key.pdf"))
        self.assertTrue(
            s3_file_regex_match(
                "/api/method/frappe_s3_attachment.controller.generate_file?key=123"
            )
        )
        self.assertFalse(s3_file_regex_match("/files/sample.pdf"))
        self.assertFalse(s3_file_regex_match("/private/files/sample.pdf"))

    @patch("os.replace")
    @patch("os.path.exists", return_value=True)
    @patch("os.makedirs")
    @patch("frappe_s3_attachment.controller.boto3.client")
    def test_download_file_from_s3_streaming(
        self, mock_boto_client, mock_makedirs, mock_exists, mock_replace
    ):
        from frappe_s3_attachment.controller import S3Operations
        s3_client_mock = MagicMock()
        mock_boto_client.return_value = s3_client_mock
        frappe.get_doc.return_value = MagicMock(
            aws_key="key",
            aws_secret="secret",
            region_name="us-east-1",
            bucket_name="mybucket",
            folder_name=None,
            do_not_delete_local_files=0,
            signed_url_expiry_time=120
        )

        ops = S3Operations()
        ops.download_file_from_s3("2026/08/key.pdf", "/sites/mysite/public/files/key.pdf")

        mock_makedirs.assert_called_once_with("/sites/mysite/public/files", exist_ok=True)
        s3_client_mock.download_file.assert_called_once_with(
            Bucket="mybucket",
            Key="2026/08/key.pdf",
            Filename="/sites/mysite/public/files/key.pdf.tmp"
        )
        mock_replace.assert_called_once_with(
            "/sites/mysite/public/files/key.pdf.tmp",
            "/sites/mysite/public/files/key.pdf"
        )

    @patch("frappe.publish_realtime")
    @patch("frappe.db.commit")
    @patch("frappe.db.sql")
    def test_update_migration_progress(self, mock_sql, mock_commit, mock_publish):
        from frappe_s3_attachment.controller import update_migration_progress
        frappe.utils.now_datetime = MagicMock(return_value="2026-08-25 13:45:00")

        update_migration_progress(
            migration_doc_name="S3MIG-00001",
            current_phase="Phase 1/2: Restoring S3 File entries",
            current_file="S3F-0001: test.png",
            total_scanned=50,
            successful=45,
            skipped=3,
            failed=2,
            total_expected=100,
            user="Administrator"
        )

        mock_sql.assert_called_once()
        sql_query = mock_sql.call_args[0][0]
        self.assertIn("UPDATE `tabS3 Migration`", sql_query)
        self.assertIn("current_phase = %s", sql_query)
        self.assertIn("progress_percentage = %s", sql_query)
        mock_commit.assert_called_once()

        mock_publish.assert_called_once()
        event_name = mock_publish.call_args[0][0]
        event_payload = mock_publish.call_args[0][1]
        self.assertEqual(event_name, "s3_migration_progress")
        self.assertEqual(event_payload["migration_doc"], "S3MIG-00001")
        self.assertEqual(event_payload["progress_percentage"], 50.0)
        self.assertEqual(event_payload["successful_files"], 45)

    def test_s3_file_regex_match_http_and_https(self):
        self.assertTrue(s3_file_regex_match("https://s3.amazonaws.com/bucket/key.pdf"))
        self.assertTrue(s3_file_regex_match("http://s3.amazonaws.com/bucket/key.pdf"))
        self.assertTrue(s3_file_regex_match("http://localhost:9000/bucket/key.pdf"))
        self.assertTrue(
            s3_file_regex_match(
                "/api/method/frappe_s3_attachment.controller.generate_file?key=123"
            )
        )
        self.assertFalse(s3_file_regex_match("/files/sample.pdf"))
        self.assertFalse(s3_file_regex_match("/private/files/sample.pdf"))
        self.assertIsNone(s3_file_regex_match(""))
        self.assertIsNone(s3_file_regex_match(None))

    def test_get_local_filepath_normalization(self):
        from frappe_s3_attachment.controller import get_local_filepath
        site_path = "/sites/mysite"

        # Public tests
        p1, u1 = get_local_filepath("/files/image.png", is_private=0, site_path=site_path)
        self.assertEqual(p1.replace("\\", "/"), "/sites/mysite/public/files/image.png")
        self.assertEqual(u1, "/files/image.png")

        p2, u2 = get_local_filepath("files/image.png", is_private=0, site_path=site_path)
        self.assertEqual(p2.replace("\\", "/"), "/sites/mysite/public/files/image.png")
        self.assertEqual(u2, "/files/image.png")

        p3, u3 = get_local_filepath("/public/files/image.png", is_private=0, site_path=site_path)
        self.assertEqual(p3.replace("\\", "/"), "/sites/mysite/public/files/image.png")
        self.assertEqual(u3, "/files/image.png")

        # Private tests
        pr1, ur1 = get_local_filepath("/private/files/doc.pdf", is_private=1, site_path=site_path)
        self.assertEqual(pr1.replace("\\", "/"), "/sites/mysite/private/files/doc.pdf")
        self.assertEqual(ur1, "/private/files/doc.pdf")

        pr2, ur2 = get_local_filepath("private/files/doc.pdf", is_private=1, site_path=site_path)
        self.assertEqual(pr2.replace("\\", "/"), "/sites/mysite/private/files/doc.pdf")
        self.assertEqual(ur2, "/private/files/doc.pdf")

        pr3, ur3 = get_local_filepath("/files/doc.pdf", is_private=1, site_path=site_path)
        self.assertEqual(pr3.replace("\\", "/"), "/sites/mysite/private/files/doc.pdf")
        self.assertEqual(ur3, "/private/files/doc.pdf")

    @patch("os.remove")
    @patch("os.path.exists", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.get_value", return_value="FILE-001")
    @patch("frappe.get_all")
    def test_smart_remigration_reuses_existing_s3_file(
        self, mock_get_all, mock_get_value, mock_get_doc, mock_exists, mock_remove
    ):
        from frappe_s3_attachment.controller import upload_existing_files_s3
        frappe.utils.get_site_path.return_value = "/sites/mysite"

        mock_file_doc = MagicMock()
        mock_file_doc.name = "FILE-001"
        mock_file_doc.file_url = "/files/reused.pdf"
        mock_file_doc.file_name = "reused.pdf"
        mock_file_doc.is_private = 0
        mock_file_doc.attached_to_doctype = "Item"
        mock_file_doc.attached_to_name = "ITEM-001"
        mock_get_doc.return_value = mock_file_doc

        # Return existing S3 File record
        mock_get_all.side_effect = [
            [{"name": "S3F-0001", "s3_key": "2026/08/reused.pdf", "status": "Restored"}], # S3 File query
            [{"name": "FILE-001", "file_name": "reused.pdf", "attached_to_doctype": None, "attached_to_name": None, "is_private": 0, "content_hash": None}] # matching files
        ]

        with patch("frappe_s3_attachment.controller.S3Operations") as mock_s3_ops_cls:
            mock_s3_inst = MagicMock()
            mock_s3_inst.BUCKET = "test-bucket"
            mock_s3_inst.do_not_delete_local_files = 0
            mock_s3_inst.S3_CLIENT.meta.endpoint_url = "https://s3.amazonaws.com"
            mock_s3_inst.verify_s3_object_exists.return_value = True
            mock_s3_ops_cls.return_value = mock_s3_inst

            existing_s3_doc_mock = MagicMock()
            def get_doc_side_effect(doctype, name):
                if doctype == "File":
                    return mock_file_doc
                if doctype == "S3 File":
                    return existing_s3_doc_mock
                return MagicMock()
            mock_get_doc.side_effect = get_doc_side_effect

            updated = upload_existing_files_s3("FILE-001")
            self.assertIn("FILE-001", updated)

            # verify_s3_object_exists should be called for existing key
            mock_s3_inst.verify_s3_object_exists.assert_called_with("2026/08/reused.pdf")
            # upload_files_to_s3_with_key should NOT be called since object was already on S3
            mock_s3_inst.upload_files_to_s3_with_key.assert_not_called()
            # Existing S3 File doc status should be updated to Active
            self.assertEqual(existing_s3_doc_mock.status, "Active")
            existing_s3_doc_mock.save.assert_called_once()

    @patch("frappe_s3_attachment.controller.S3Operations")
    def test_disable_s3_upload_skips_upload(self, mock_s3_ops_cls):
        from frappe_s3_attachment.controller import file_upload_to_s3, upload_existing_files_s3
        s3_inst = MagicMock()
        s3_inst.disable_s3_upload = 1
        mock_s3_ops_cls.return_value = s3_inst

        doc = MagicMock()
        doc.file_url = "/files/test.png"
        doc.is_private = 0
        file_upload_to_s3(doc, "after_insert")

        # S3 upload functions should never be called when disable_s3_upload is True
        s3_inst.upload_files_to_s3_with_key.assert_not_called()

        res = upload_existing_files_s3("FILE-001")
        self.assertEqual(res, [])

    @patch("os.remove")
    @patch("os.path.exists", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.get_all", return_value=[{"name": "FILE-001", "file_name": "test.png", "attached_to_doctype": None, "attached_to_name": None, "is_private": 0, "content_hash": "hash123"}])
    @patch("frappe.new_doc")
    @patch("frappe.db.sql")
    def test_do_not_change_file_url_keeps_local_url_and_file(
        self, mock_sql, mock_new_doc, mock_get_all, mock_get_doc, mock_exists, mock_remove
    ):
        from frappe_s3_attachment.controller import file_upload_to_s3
        frappe.utils.get_site_path.return_value = "/sites/mysite"
        frappe.local.conf.get.return_value = []

        doc = MagicMock()
        doc.name = "FILE-001"
        doc.file_url = "/files/local_serve.png"
        doc.file_name = "local_serve.png"
        doc.is_private = 0
        doc.attached_to_doctype = None
        doc.attached_to_name = None

        with patch("frappe_s3_attachment.controller.S3Operations") as mock_s3_ops_cls:
            s3_inst = MagicMock()
            s3_inst.disable_s3_upload = 0
            s3_inst.do_not_change_file_url = 1
            s3_inst.do_not_delete_local_files = 0  # Even if deletion is not checked, file should be preserved!
            s3_inst.BUCKET = "test-bucket"
            s3_inst.S3_CLIENT.meta.endpoint_url = "https://s3.amazonaws.com"
            s3_inst.upload_files_to_s3_with_key.return_value = "2026/08/local_serve.png"
            s3_inst.verify_s3_object_exists.return_value = True
            mock_s3_ops_cls.return_value = s3_inst

            file_upload_to_s3(doc, "after_insert")

            # Local file must NOT be deleted
            mock_remove.assert_not_called()
            # doc.file_url must NOT be changed to S3 URL
            self.assertEqual(doc.file_url, "/files/local_serve.png")
            # S3 File record should still be created for tracking
            mock_new_doc.assert_called_with("S3 File")

    @patch("os.path.exists")
    @patch("os.path.getsize", return_value=1024)
    @patch("frappe.get_all")
    @patch("frappe.db.sql")
    @patch("frappe.db.exists")
    def test_scan_storage_space(self, mock_exists_db, mock_sql, mock_get_all, mock_getsize, mock_exists_fs):
        from frappe_s3_attachment.controller import scan_storage_space
        frappe.utils.get_site_path.return_value = "/sites/mysite"
        mock_exists_fs.return_value = True

        # S3 Files (Duplicate local files)
        mock_get_all.return_value = [
            {"name": "S3F-001", "original_file_url": "/files/test1.pdf", "is_private": 0, "file_name": "test1.pdf"}
        ]
        # sql side effect for tabFile s3 urls, attached files, unlinked files, unreferenced files
        mock_sql.side_effect = [
            [], # tabFile with S3 url
            [{"name": "FILE-002", "file_name": "orphan.png", "file_url": "/files/orphan.png", "file_size": 2048, "attached_to_doctype": "Item", "attached_to_name": "DELETED-ITEM", "is_private": 0}], # attached files
            [{"name": "FILE-003", "file_name": "unlinked.pdf", "file_url": "/files/unlinked.pdf", "file_size": 4096, "is_private": 0}], # unlinked files
            [{"file_url": "/files/test1.pdf"}], # db file urls
            [{"original_file_url": "/files/test1.pdf"}], # s3 orig urls
            [], # s3 keys
            []  # content hashes
        ]
        mock_exists_db.return_value = False # Item does not exist -> orphan!

        with patch("frappe_s3_attachment.controller.S3Operations") as mock_s3_ops_cls:
            s3_inst = MagicMock()
            s3_inst.S3_CLIENT = None
            mock_s3_ops_cls.return_value = s3_inst

            res = scan_storage_space(grace_period_days=7)
            self.assertEqual(res["status"], "success")
            self.assertGreater(res["summary"]["total_files"], 0)
            self.assertEqual(res["summary"]["duplicate_local_files"]["count"], 1)
            self.assertEqual(res["summary"]["orphaned_attachments"]["count"], 1)
            self.assertEqual(res["summary"]["unlinked_files"]["count"], 1)

    @patch("os.remove")
    @patch("os.path.exists", return_value=True)
    @patch("os.path.getsize", return_value=1024)
    @patch("frappe.get_all")
    @patch("frappe.db.sql")
    @patch("frappe.new_doc")
    def test_process_storage_cleanup_duplicate_local_files(
        self, mock_new_doc, mock_sql, mock_get_all, mock_getsize, mock_exists, mock_remove
    ):
        from frappe_s3_attachment.controller import process_storage_cleanup
        frappe.utils.get_site_path.return_value = "/sites/mysite"

        mock_mig_doc = MagicMock()
        mock_mig_doc.name = "S3MIG-001"
        mock_new_doc.return_value = mock_mig_doc

        mock_get_all.return_value = [
            {"name": "S3F-001", "s3_key": "2026/08/test.pdf", "original_file_url": "/files/test.pdf", "is_private": 0, "file_name": "test.pdf"}
        ]

        with patch("frappe_s3_attachment.controller.S3Operations") as mock_s3_ops_cls:
            s3_inst = MagicMock()
            s3_inst.verify_s3_object_exists.return_value = True
            mock_s3_ops_cls.return_value = s3_inst

            process_storage_cleanup(categories=["duplicate_local_files"])

            # Local disk file must be deleted because S3 object is verified!
            mock_remove.assert_called_once()
            # Direct SQL update should have finalized status as Completed
            mock_sql.assert_called()


