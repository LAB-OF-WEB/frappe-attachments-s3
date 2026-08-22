# -*- coding: utf-8 -*-
# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import os
import frappe
from frappe.model.document import Document
from frappe_s3_attachment.controller import S3Operations


class S3File(Document):

    @frappe.whitelist()
    def restore_to_disk(self):
        """
        Download the object from AWS S3, write it back to the local server disk,
        and revert all modified tabFile records and DocType image fields back to original_file_url.
        """
        if self.status == "Restored":
            frappe.msgprint(frappe._("This file has already been restored to disk."))
            return {"status": "already_restored"}

        s3_upload = S3Operations()
        site_path = frappe.utils.get_site_path()

        # Determine target local file path
        if not self.is_private:
            local_file_path = site_path + "/public" + self.original_file_url
        else:
            local_file_path = site_path + self.original_file_url

        # Ensure destination directory exists
        os.makedirs(os.path.dirname(local_file_path), exist_ok=True)

        # 1. Download file bytes from S3
        try:
            s3_obj = s3_upload.read_file_from_s3(self.s3_key)
            file_body = s3_obj["Body"].read()
            with open(local_file_path, "wb") as f:
                f.write(file_body)
        except Exception as e:
            frappe.logger().error(
                "Failed to download and write file from S3 (key: {0}): {1}".format(self.s3_key, str(e))
            )
            frappe.throw(frappe._("Failed to restore file from S3: {0}").format(str(e)))

        # 2. Revert tabFile records
        for link in self.links:
            if link.file_doc:
                frappe.db.sql(
                    """UPDATE `tabFile` SET file_url=%s, content_hash=%s WHERE name=%s""",
                    (self.original_file_url, self.content_hash, link.file_doc),
                )
            if link.attached_to_doctype and link.attached_to_name and link.image_field:
                try:
                    frappe.db.set_value(
                        link.attached_to_doctype,
                        link.attached_to_name,
                        link.image_field,
                        self.original_file_url,
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
            (self.original_file_url, self.content_hash, self.s3_key),
        )

        self.status = "Restored"
        self.restored_at = frappe.utils.now_datetime()
        self.save(ignore_permissions=True)
        frappe.db.commit()

        frappe.msgprint(
            frappe._("File restored successfully to {0} and all database links reverted.").format(
                self.original_file_url
            )
        )
        return {"status": "success", "file_path": local_file_path}
