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

		frappe.realtime.off('s3_storage_scan_complete');
		frappe.realtime.on('s3_storage_scan_complete', function(data) {
			frappe.dom.unfreeze();
			if (data && data.status === 'success') {
				show_storage_scan_dialog(frm, data);
			} else {
				frappe.msgprint(data.message || __('Error scanning storage space.'), __('Scan Error'));
			}
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
		frappe.dom.freeze(__('Scanning storage space in background queue (RQ)...'));
		frappe.call({
			method: 'frappe_s3_attachment.controller.enqueue_scan_storage_space',
			args: {
				grace_period_days: frm.doc.unlinked_grace_period_days || 7
			},
			callback: function (r) {
				if (r.message && r.message.status === 'enqueued') {
					frappe.show_alert({
						message: __('Storage scan enqueued in background. The preview dialog will open automatically when ready.'),
						indicator: 'blue'
					}, 7);
				} else {
					frappe.dom.unfreeze();
					frappe.msgprint(__('Unable to enqueue storage scan.'));
				}
			}
		});
	},
	reclaim_disk_storage: function (frm) {
		frappe.confirm(
			__('Are you sure you want to reclaim storage from local server disk in the background?'),
			function () {
				frappe.call({
					method: 'frappe_s3_attachment.controller.reclaim_storage_space',
					args: {
						target: 'disk',
						grace_period_days: frm.doc.unlinked_grace_period_days || 7
					},
					freeze: true,
					freeze_message: __('Queueing Disk storage cleanup...'),
					callback: function (resp) {
						if (resp.message && resp.message.status === 'enqueued') {
							frappe.show_alert({
								message: __('Disk storage reclamation has been enqueued in the background.'),
								indicator: 'green'
							}, 7);
						} else {
							frappe.msgprint(__('Unable to queue disk cleanup job.'));
						}
					}
				});
			}
		);
	},
	reclaim_s3_storage: function (frm) {
		frappe.confirm(
			__('Are you sure you want to reclaim storage from AWS S3 cloud bucket in the background?'),
			function () {
				frappe.call({
					method: 'frappe_s3_attachment.controller.reclaim_storage_space',
					args: {
						target: 's3',
						grace_period_days: frm.doc.unlinked_grace_period_days || 7
					},
					freeze: true,
					freeze_message: __('Queueing S3 storage cleanup...'),
					callback: function (resp) {
						if (resp.message && resp.message.status === 'enqueued') {
							frappe.show_alert({
								message: __('S3 storage reclamation has been enqueued in the background.'),
								indicator: 'green'
							}, 7);
						} else {
							frappe.msgprint(__('Unable to queue S3 cleanup job.'));
						}
					}
				});
			}
		);
	}
});

function show_storage_scan_dialog(frm, scan_data) {
	var disk = scan_data.disk_summary;
	var s3 = scan_data.s3_summary;
	var total_mb = scan_data.total_mb;
	var total_files = scan_data.total_files;

	var d = new frappe.ui.Dialog({
		title: __('Storage Optimization & Space Savings Preview'),
		fields: [
			{
				fieldname: 'html_intro',
				fieldtype: 'HTML',
				options: '<div class="alert alert-info" style="margin-bottom:15px;">' +
					'<b>' + __('Total Space Reclaimable:') + ' ' + total_mb + ' MB</b> (' + total_files + ' ' + __('files/objects') + ')<br>' +
					'<b>' + __('Local Disk:') + ' ' + disk.total_mb + ' MB</b> | <b>' + __('S3 Cloud:') + ' ' + s3.total_mb + ' MB</b>' +
					'</div>'
			},
			{
				fieldname: 'sec_disk',
				fieldtype: 'Section Break',
				label: __('Local Disk Storage Reclamation ({0} MB)', [disk.total_mb])
			},
			{
				fieldname: 'duplicate_local_files',
				fieldtype: 'Check',
				label: __('Duplicate Local Files (Stored on S3, redundant copy on disk): {0} files ({1} MB)', [disk.duplicate_local_files.count, disk.duplicate_local_files.mb]),
				default: disk.duplicate_local_files.count > 0 ? 1 : 0
			},
			{
				fieldname: 'orphaned_disk_attachments',
				fieldtype: 'Check',
				label: __('Orphaned Disk Files (Parent DocType was deleted): {0} files ({1} MB)', [disk.orphaned_disk_attachments.count, disk.orphaned_disk_attachments.mb]),
				default: disk.orphaned_disk_attachments.count > 0 ? 1 : 0
			},
			{
				fieldname: 'unlinked_disk_files',
				fieldtype: 'Check',
				label: __('Abandoned Unlinked Disk Files (> {0} days old): {1} files ({2} MB)', [frm.doc.unlinked_grace_period_days || 7, disk.unlinked_disk_files.count, disk.unlinked_disk_files.mb]),
				default: disk.unlinked_disk_files.count > 0 ? 1 : 0
			},
			{
				fieldname: 'unreferenced_disk_files',
				fieldtype: 'Check',
				label: __('Unreferenced Physical Disk Files (No DB record): {0} files ({1} MB)', [disk.unreferenced_disk_files.count, disk.unreferenced_disk_files.mb]),
				default: disk.unreferenced_disk_files.count > 0 ? 1 : 0
			},
			{
				fieldname: 'sec_s3',
				fieldtype: 'Section Break',
				label: __('AWS S3 Cloud Storage Reclamation ({0} MB)', [s3.total_mb])
			},
			{
				fieldname: 'orphaned_s3_attachments',
				fieldtype: 'Check',
				label: __('Orphaned S3 Cloud Objects (Parent DocType was deleted): {0} objects ({1} MB)', [s3.orphaned_s3_attachments.count, s3.orphaned_s3_attachments.mb]),
				default: s3.orphaned_s3_attachments.count > 0 ? 1 : 0
			},
			{
				fieldname: 'unlinked_s3_files',
				fieldtype: 'Check',
				label: __('Abandoned Unlinked S3 Objects (> {0} days old): {1} objects ({2} MB)', [frm.doc.unlinked_grace_period_days || 7, s3.unlinked_s3_files.count, s3.unlinked_s3_files.mb]),
				default: s3.unlinked_s3_files.count > 0 ? 1 : 0
			},
			{
				fieldname: 'unreferenced_s3_objects',
				fieldtype: 'Check',
				label: __('Unreferenced S3 Bucket Objects (No DB record): {0} objects ({1} MB)', [s3.unreferenced_s3_objects.count, s3.unreferenced_s3_objects.mb]),
				default: s3.unreferenced_s3_objects.count > 0 ? 1 : 0
			}
		],
		primary_action_label: __('Reclaim All Selected Space'),
		primary_action: function () {
			var vals = d.get_values();
			var selected = [];
			if (vals.duplicate_local_files) selected.push('duplicate_local_files');
			if (vals.orphaned_disk_attachments) selected.push('orphaned_disk_attachments');
			if (vals.unlinked_disk_files) selected.push('unlinked_disk_files');
			if (vals.unreferenced_disk_files) selected.push('unreferenced_disk_files');
			if (vals.orphaned_s3_attachments) selected.push('orphaned_s3_attachments');
			if (vals.unlinked_s3_files) selected.push('unlinked_s3_files');
			if (vals.unreferenced_s3_objects) selected.push('unreferenced_s3_objects');

			if (selected.length === 0) {
				frappe.msgprint(__('Please select at least one category to reclaim.'));
				return;
			}
			d.hide();
			frappe.call({
				method: 'frappe_s3_attachment.controller.reclaim_storage_space',
				args: {
					target: 'all',
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

	d.set_secondary_action_label(__('Reclaim Disk Storage'));
	d.set_secondary_action(function () {
		var vals = d.get_values();
		var selected = [];
		if (vals.duplicate_local_files) selected.push('duplicate_local_files');
		if (vals.orphaned_disk_attachments) selected.push('orphaned_disk_attachments');
		if (vals.unlinked_disk_files) selected.push('unlinked_disk_files');
		if (vals.unreferenced_disk_files) selected.push('unreferenced_disk_files');

		if (selected.length === 0) {
			selected = ['duplicate_local_files', 'orphaned_disk_attachments', 'unlinked_disk_files', 'unreferenced_disk_files'];
		}
		d.hide();
		frappe.call({
			method: 'frappe_s3_attachment.controller.reclaim_storage_space',
			args: {
				target: 'disk',
				categories: selected,
				grace_period_days: frm.doc.unlinked_grace_period_days || 7
			},
			freeze: true,
			freeze_message: __('Queueing Disk storage cleanup...'),
			callback: function (resp) {
				if (resp.message && resp.message.status === 'enqueued') {
					frappe.show_alert({
						message: __('Disk storage reclamation has been enqueued in the background.'),
						indicator: 'green'
					}, 7);
				} else {
					frappe.msgprint(__('Unable to queue disk cleanup job.'));
				}
			}
		});
	});

	d.show();
}



