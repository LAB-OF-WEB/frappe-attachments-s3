// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.listview_settings['S3 File'] = {
	onload: function(listview) {
		listview.page.clear_primary_action();
	},
	refresh: function(listview) {
		listview.page.clear_primary_action();
	}
};
