// Copyright (c) 2018, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on('S3 File Attachment', {
	refresh: function(frm) {
		frappe.realtime.off('s3_migration_complete');
		frappe.realtime.on('s3_migration_complete', function(data) {
			frappe.msgprint(data.message || __('S3 Migration completed.'), __('S3 Migration'));
		});

		frappe.realtime.off('s3_restore_complete');
		frappe.realtime.on('s3_restore_complete', function(data) {
			frappe.msgprint(data.message || __('S3 Restore completed.'), __('S3 Restore'));
		});
	},
	migrate_existing_files: function (frm) {
		frappe.confirm(
			__('Are you sure you want to migrate all local files to S3 in the background?'),
			function () {
				frappe.call({
					method: 'frappe_s3_attachment.controller.migrate_existing_files',
					freeze: true,
					freeze_message: __('Queueing background migration...'),
					callback: function (r) {
						if (r.message && r.message.status === 'enqueued') {
							frappe.show_alert({
								message: __('File migration has been enqueued in the background. You will be notified when complete.'),
								indicator: 'green'
							}, 7);
						} else if (r.message && r.message.status === 'disabled') {
							frappe.msgprint(r.message.message || __('S3 upload is currently disabled in settings.'));
						} else {
							frappe.msgprint(__('Unable to queue migration job. Please check error logs.'));
						}
					}
				});
			}
		);
	},
	restore_s3_files: function (frm) {
		frappe.confirm(
			__('Are you sure you want to fetch all files from S3 back to local disk in the background? (Note: Files will NOT be deleted from S3).'),
			function () {
				frappe.call({
					method: 'frappe_s3_attachment.controller.restore_all_s3_files',
					freeze: true,
					freeze_message: __('Queueing background restore...'),
					callback: function (r) {
						if (r.message && r.message.status === 'enqueued') {
							frappe.show_alert({
								message: __('File restore has been enqueued in the background. You will be notified when complete.'),
								indicator: 'green'
							}, 7);
						} else {
							frappe.msgprint(__('Unable to queue restore job. Please check error logs.'));
						}
					}
				});
			}
		);
	}
});

