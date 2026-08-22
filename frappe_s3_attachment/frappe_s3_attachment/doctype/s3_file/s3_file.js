// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on('S3 File', {
	refresh: function(frm) {
		if (!frm.is_new() && frm.doc.status !== 'Restored') {
			frm.add_custom_button(__('Restore to Disk'), function() {
				frappe.confirm(
					__('Are you sure you want to download this file from S3 to local disk and revert all linked document URLs back to the original local path ({0})?', [frm.doc.original_file_url]),
					function() {
						frappe.call({
							method: 'restore_to_disk',
							doc: frm.doc,
							freeze: true,
							freeze_message: __('Restoring file from S3 to local disk...'),
							callback: function(r) {
								if (r.message && r.message.status === 'success') {
									frappe.show_alert({
										message: __('File restored successfully.'),
										indicator: 'green'
									}, 5);
									frm.reload_doc();
								}
							}
						});
					}
				);
			}).addClass('btn-primary');
		}
	}
});
