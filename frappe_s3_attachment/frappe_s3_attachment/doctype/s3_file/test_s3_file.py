# -*- coding: utf-8 -*-
# Copyright (c) 2026, Frappe and Contributors
# See license.txt
from __future__ import unicode_literals

import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock dependencies if not installed in standalone environment
if "frappe" not in sys.modules:
    class MockDocument:
        def __init__(self, *args, **kwargs):
            self.name = kwargs.get("name", "MOCK-S3F-001")
            self.flags = MagicMock()
            for k, v in kwargs.items():
                setattr(self, k, v)

        def get(self, key, default=None):
            return getattr(self, key, default)

        def set(self, key, val):
            setattr(self, key, val)

        def append(self, key, val):
            if not hasattr(self, key) or not isinstance(getattr(self, key), list):
                setattr(self, key, [])
            getattr(self, key).append(val)

        def save(self, *args, **kwargs):
            pass

        def insert(self, *args, **kwargs):
            pass

    def _whitelist(*args, **kwargs):
        if len(args) == 1 and callable(args[0]):
            return args[0]

        def decorator(fn):
            return fn

        return decorator

    m_frappe = MagicMock()
    m_frappe.whitelist = _whitelist
    m_frappe._ = lambda s, *a, **kw: s
    m_frappe.flags = MagicMock(in_test=True)
    m_frappe.local = MagicMock()
    m_frappe.local.conf = MagicMock()
    m_frappe.local.conf.get.return_value = []
    m_frappe.local.response = {}
    m_frappe.session = MagicMock(user="Administrator")
    m_frappe.db.count.return_value = 0
    m_frappe.db.exists.return_value = True
    m_frappe.has_permission.return_value = True
    m_frappe.get_roles.return_value = ["System Manager"]
    m_frappe.utils.get_site_path.return_value = "/sites/mysite"
    m_frappe.utils.now_datetime.return_value = "2026-08-22 23:00:00"
    m_frappe.model.document.Document = MockDocument

    sys.modules["frappe"] = m_frappe
    sys.modules["frappe.utils"] = m_frappe.utils
    sys.modules["frappe.model"] = m_frappe.model
    sys.modules["frappe.model.document"] = m_frappe.model.document

for mod in [
    "boto3",
    "botocore",
    "botocore.client",
    "botocore.exceptions",
    "magic",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

import frappe  # noqa: E402
from frappe_s3_attachment.controller import get_local_filepath  # noqa: E402
from frappe_s3_attachment.frappe_s3_attachment.doctype.s3_file.s3_file import S3File  # noqa: E402


class TestS3File(unittest.TestCase):

    def setUp(self):
        frappe.reset_mock()
        frappe.flags.in_test = True
        frappe.utils.get_site_path.return_value = "/sites/mysite"
        frappe.utils.now_datetime.return_value = "2026-08-22 23:00:00"

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
        expected_path, _ = get_local_filepath(doc.original_file_url, doc.is_private, "/sites/mysite")
        s3_inst.download_file_from_s3.assert_called_once_with(
            "2026/08/22/Item/KEY_test.png", expected_path
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
        expected_path, _ = get_local_filepath(doc.original_file_url, doc.is_private, "/sites/mysite")
        s3_inst.download_file_from_s3.assert_called_once_with(
            "2026/08/22/Item/KEY_batch.png", expected_path
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
        expected_path, _ = get_local_filepath(doc.original_file_url, doc.is_private, "/sites/mysite")
        s3_inst.download_file_from_s3.assert_called_once_with(
            "2026/08/22/Doc/KEY_secret.pdf",
            expected_path
        )
        mock_commit.assert_called_once()
