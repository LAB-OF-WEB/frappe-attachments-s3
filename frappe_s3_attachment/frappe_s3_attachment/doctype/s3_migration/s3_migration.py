# -*- coding: utf-8 -*-
# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document

class S3Migration(Document):
	def before_insert(self):
		if (
			not getattr(self.flags, "ignore_permissions", False)
			and not getattr(frappe.flags, "in_test", False)
			and not getattr(frappe.flags, "in_install", False)
			and not getattr(frappe.flags, "in_migrate", False)
		):
			frappe.throw(
				frappe._("Manual creation of S3 Migration records is not permitted. Migrations must be initiated from S3 File Attachment settings."),
				frappe.PermissionError,
			)

