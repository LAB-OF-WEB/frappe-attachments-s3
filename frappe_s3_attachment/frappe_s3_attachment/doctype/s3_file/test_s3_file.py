# -*- coding: utf-8 -*-
# Copyright (c) 2026, Frappe and Contributors
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
from frappe_s3_attachment.frappe_s3_attachment.doctype.s3_file.s3_file import S3File


class TestS3File(unittest.TestCase):

    def setUp(self):
        frappe.reset_mock()
        frappe.utils.get_site_path = MagicMock(return_value="/sites/mysite")
        frappe.utils.now_datetime = MagicMock(return_value="2026-08-22 23:00:00")

    @patch("frappe.msgprint")
    @patch("os.makedirs")
    @patch("frappe.db.commit")
    @patch("frappe.db.set_value")
    @patch("frappe.db.sql")
    @patch("frappe_s3_attachment.frappe_s3_attachment.doctype.s3_file.s3_file.S3Operations")
    def test_restore_to_disk_public_file(
        self, mock_s3_ops, mock_db_sql, mock_set_value, mock_commit, mock_makedirs, mock_msgprint
    ):
        s3_inst = MagicMock()
        mock_s3_ops.return_value = s3_inst

        doc = S3File()
        doc.file_name = "test.png"
        doc.s3_key = "2026/08/22/Item/KEY_test.png"
        doc.original_file_url = "/files/test.png"
        doc.is_private = 0
        doc.content_hash = "abc123hash"
        doc.status = "Active"
        doc.save = MagicMock()

        link1 = MagicMock()
        link1.file_doc = "FILE-001"
        link1.attached_to_doctype = "Item"
        link1.attached_to_name = "ITEM-001"
        link1.image_field = "image"
        link1.restored = 0

        doc.links = [link1]

        res = doc.restore_to_disk()

        self.assertEqual(res["status"], "success")
        self.assertEqual(doc.status, "Restored")
        self.assertEqual(link1.restored, 1)
        mock_makedirs.assert_called_once()
        s3_inst.download_file_from_s3.assert_called_once_with(
            "2026/08/22/Item/KEY_test.png", "/sites/mysite/public/files/test.png"
        )
        mock_set_value.assert_called_once_with("Item", "ITEM-001", "image", "/files/test.png")
        mock_commit.assert_called_once()
        mock_msgprint.assert_called_once()

    @patch("frappe.msgprint")
    @patch("os.makedirs")
    @patch("frappe.db.commit")
    @patch("frappe.db.set_value")
    @patch("frappe.db.sql")
    def test_restore_to_disk_batch_mode_reusable_client(
        self, mock_db_sql, mock_set_value, mock_commit, mock_makedirs, mock_msgprint
    ):
        s3_inst = MagicMock()

        doc = S3File()
        doc.file_name = "test_batch.png"
        doc.s3_key = "2026/08/22/Item/KEY_batch.png"
        doc.original_file_url = "/files/test_batch.png"
        doc.is_private = 0
        doc.content_hash = "batchhash"
        doc.status = "Active"
        doc.save = MagicMock()
        doc.links = []

        res = doc.restore_to_disk(s3_operations=s3_inst, batch_mode=True)

        self.assertEqual(res["status"], "success")
        self.assertEqual(doc.status, "Restored")
        s3_inst.download_file_from_s3.assert_called_once_with(
            "2026/08/22/Item/KEY_batch.png", "/sites/mysite/public/files/test_batch.png"
        )
        # In batch mode, frappe.msgprint should not be called to avoid message_log memory bloat
        mock_msgprint.assert_not_called()
        mock_commit.assert_called_once()

    @patch("frappe.msgprint")
    @patch("os.makedirs")
    @patch("frappe.db.commit")
    @patch("frappe.db.set_value")
    @patch("frappe.db.sql")
    def test_restore_to_disk_private_file(
        self, mock_db_sql, mock_set_value, mock_commit, mock_makedirs, mock_msgprint
    ):
        s3_inst = MagicMock()

        doc = S3File()
        doc.file_name = "secret.pdf"
        doc.s3_key = "2026/08/22/Doc/KEY_secret.pdf"
        doc.original_file_url = "/private/files/secret.pdf"
        doc.is_private = 1
        doc.content_hash = "secrethash"
        doc.status = "Active"
        doc.save = MagicMock()
        doc.links = []

        res = doc.restore_to_disk(s3_operations=s3_inst, batch_mode=True)

        self.assertEqual(res["status"], "success")
        self.assertEqual(doc.status, "Restored")
        # Private file should be placed in /sites/mysite/private/files/secret.pdf
        s3_inst.download_file_from_s3.assert_called_once_with(
            "2026/08/22/Doc/KEY_secret.pdf",
            os.path.join("/sites/mysite", "private", "files", "secret.pdf")
        )
        mock_commit.assert_called_once()
