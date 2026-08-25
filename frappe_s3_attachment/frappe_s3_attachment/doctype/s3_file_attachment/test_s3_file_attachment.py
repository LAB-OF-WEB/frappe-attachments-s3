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
