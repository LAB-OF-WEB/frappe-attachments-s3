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
		frappe.realtime.off('s3_cleanup_complete');
		frappe.realtime.on('s3_cleanup_complete', function(data) {
			frappe.msgprint(data.message || __('Storage cleanup completed.'), __('Storage Optimization'));
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
	},
	scan_storage_space: function (frm) {
		frappe.call({
			method: 'frappe_s3_attachment.controller.scan_storage_space',
			args: {
				grace_period_days: frm.doc.unlinked_grace_period_days || 7
			},
			freeze: true,
			freeze_message: __('Scanning database, local files, and S3 for space savings...'),
			callback: function (r) {
				if (r.message && r.message.status === 'success') {
					var s = r.message.summary;
					var d = new frappe.ui.Dialog({
						title: __('Storage Optimization & Space Savings Preview'),
						fields: [
							{
								fieldname: 'html_intro',
								fieldtype: 'HTML',
								options: '<div class="alert alert-info" style="margin-bottom:15px;">' +
									'<b>' + __('Total Space Reclaimable:') + ' ' + s.total_mb + ' MB</b> (' + s.total_files + ' ' + __('files/objects') + ')<br>' +
									'<small>' + __('Select the categories you wish to clean below.') + '</small>' +
									'</div>'
							},
							{
								fieldname: 'duplicate_local_files',
								fieldtype: 'Check',
								label: __('Duplicate Local Files (Files on S3 with redundant local copy): {0} files ({1} MB)', [s.duplicate_local_files.count, s.duplicate_local_files.mb]),
								default: s.duplicate_local_files.count > 0 ? 1 : 0
							},
							{
								fieldname: 'orphaned_attachments',
								fieldtype: 'Check',
								label: __('Orphaned Attachments (Parent DocType was deleted): {0} files ({1} MB)', [s.orphaned_attachments.count, s.orphaned_attachments.mb]),
								default: s.orphaned_attachments.count > 0 ? 1 : 0
							},
							{
								fieldname: 'unlinked_files',
								fieldtype: 'Check',
								label: __('Abandoned Unlinked Files (> {0} days old): {1} files ({2} MB)', [frm.doc.unlinked_grace_period_days || 7, s.unlinked_files.count, s.unlinked_files.mb]),
								default: s.unlinked_files.count > 0 ? 1 : 0
							},
							{
								fieldname: 'unreferenced_disk_files',
								fieldtype: 'Check',
								label: __('Unreferenced Local Disk Files: {0} files ({1} MB)', [s.unreferenced_disk_files.count, s.unreferenced_disk_files.mb]),
								default: s.unreferenced_disk_files.count > 0 ? 1 : 0
							},
							{
								fieldname: 'unreferenced_s3_objects',
								fieldtype: 'Check',
								label: __('Unreferenced S3 Bucket Objects: {0} objects ({1} MB)', [s.unreferenced_s3_objects.count, s.unreferenced_s3_objects.mb]),
								default: s.unreferenced_s3_objects.count > 0 ? 1 : 0
							}
						],
						primary_action_label: __('Reclaim Selected Space'),
						primary_action: function () {
							var vals = d.get_values();
							var selected = [];
							if (vals.duplicate_local_files) selected.push('duplicate_local_files');
							if (vals.orphaned_attachments) selected.push('orphaned_attachments');
							if (vals.unlinked_files) selected.push('unlinked_files');
							if (vals.unreferenced_disk_files) selected.push('unreferenced_disk_files');
							if (vals.unreferenced_s3_objects) selected.push('unreferenced_s3_objects');

							if (selected.length === 0) {
								frappe.msgprint(__('Please select at least one category to reclaim.'));
								return;
							}
							d.hide();
							frappe.call({
								method: 'frappe_s3_attachment.controller.reclaim_storage_space',
								args: {
									categories: selected,
									grace_period_days: frm.doc.unlinked_grace_period_days || 7
								},
								freeze: true,
								freeze_message: __('Queueing background storage cleanup...'),
								callback: function (resp) {
									if (resp.message && resp.message.status === 'enqueued') {
										frappe.show_alert({
											message: __('Storage reclamation has been enqueued in the background. Check S3 Migration logs for live progress.'),
											indicator: 'green'
										}, 7);
									} else {
										frappe.msgprint(__('Unable to queue cleanup job.'));
									}
								}
							});
						}
					});
					d.show();
				} else {
					frappe.msgprint(__('Error scanning storage space.'));
				}
			}
		});
	},
	reclaim_storage_space: function (frm) {
		frm.trigger('scan_storage_space');
	}
});


