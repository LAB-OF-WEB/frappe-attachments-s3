# -*- coding: utf-8 -*-
# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import os
import frappe
from frappe.model.document import Document
from frappe_s3_attachment.controller import S3Operations, get_local_filepath


class S3File(Document):

    @frappe.whitelist()
    def restore_to_disk(self, s3_operations=None, batch_mode=False):
        """
        Download the object from AWS S3, write it back to the local server disk,
        and revert all modified tabFile records and DocType image fields back to original_file_url.
        """
        if self.status == "Restored":
            if not batch_mode:
                frappe.msgprint(frappe._("This file has already been restored to disk."))
            return {"status": "already_restored"}

        s3_upload = s3_operations or S3Operations()
        site_path = frappe.utils.get_site_path()

        # Determine target local file path safely using normalized path resolver
        local_file_path, normalized_db_url = get_local_filepath(
            self.original_file_url, self.is_private, site_path
        )

        # Ensure destination directory exists
        os.makedirs(os.path.dirname(local_file_path), exist_ok=True)

        # 1. Download file bytes from S3 using streaming to minimize memory usage
        try:
            if hasattr(s3_upload, "download_file_from_s3"):
                s3_upload.download_file_from_s3(self.s3_key, local_file_path)
            else:
                s3_obj = s3_upload.read_file_from_s3(self.s3_key)
                body = s3_obj.get("Body") if isinstance(s3_obj, dict) else s3_obj
                temp_file_path = local_file_path + ".tmp"
                with open(temp_file_path, "wb") as f:
                    if hasattr(body, "iter_chunks"):
                        for chunk in body.iter_chunks(chunk_size=64 * 1024):
                            if chunk:
                                f.write(chunk)
                    elif hasattr(body, "read"):
                        while True:
                            chunk = body.read(64 * 1024)
                            if not chunk:
                                break
                            f.write(chunk)
                    elif isinstance(body, (bytes, bytearray)):
                        f.write(body)
                if os.path.exists(temp_file_path):
                    os.replace(temp_file_path, local_file_path)
        except Exception as e:
            temp_file_path = local_file_path + ".tmp"
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass
            frappe.logger().error(
                "Failed to download and write file from S3 (key: {0}): {1}".format(self.s3_key, str(e))
            )
            frappe.throw(frappe._("Failed to restore file from S3: {0}").format(str(e)))

        # 2. Revert tabFile records
        for link in self.links:
            if link.file_doc:
                frappe.db.sql(
                    """UPDATE `tabFile` SET file_url=%s, content_hash=%s WHERE name=%s""",
                    (normalized_db_url, self.content_hash, link.file_doc),
                )
            if link.attached_to_doctype and link.attached_to_name and link.image_field:
                try:
                    frappe.db.set_value(
                        link.attached_to_doctype,
                        link.attached_to_name,
                        link.image_field,
                        normalized_db_url,
                    )
                except Exception as e:
                    frappe.logger().warning(
                        "Could not revert image field for {0} {1}: {2}".format(
                            link.attached_to_doctype, link.attached_to_name, str(e)
                        )
                    )
            link.restored = 1

        # Also revert any matching tabFile records where content_hash or file_url matches the S3 key
        frappe.db.sql(
            """UPDATE `tabFile` SET file_url=%s, content_hash=%s WHERE content_hash=%s""",
            (normalized_db_url, self.content_hash, self.s3_key),
        )

        self.status = "Restored"
        self.restored_at = frappe.utils.now_datetime()
        self.save(ignore_permissions=True)
        frappe.db.commit()

        if not batch_mode:
            frappe.msgprint(
                frappe._("File restored successfully to {0} and all database links reverted.").format(
                    normalized_db_url
                )
            )
        return {"status": "success", "file_path": local_file_path}
