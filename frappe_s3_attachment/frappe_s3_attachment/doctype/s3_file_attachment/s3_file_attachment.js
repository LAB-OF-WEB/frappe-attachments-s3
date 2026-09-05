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
			var title = (data && data.dry_run) ? __('Storage Cleanup (Dry Run)') : __('Storage Optimization');
			frappe.msgprint(data.message || __('Storage cleanup completed.'), title);
			if (frm && frm.dashboard) {
				frm.dashboard.clear_headline();
			}
		});

		frappe.realtime.off('s3_storage_scan_complete');
		frappe.realtime.on('s3_storage_scan_complete', function(data) {
			if (data && data.status === 'success') {
				frappe.show_alert({
					message: __('Storage analysis ready: {0} MB reclaimable ({1} files).', [data.total_mb, data.total_files]),
					indicator: 'green'
				}, 10);
				if (frm && frm.dashboard) {
					frm.dashboard.set_headline(
						__('Latest Storage Scan: <b>{0} MB</b> reclaimable space. <button class="btn btn-xs btn-primary ml-2 btn-open-reclaim-hub">Open Reclamation Hub</button>', [data.total_mb]),
						'green'
					);
					frm.$wrapper.find('.btn-open-reclaim-hub').off('click').on('click', function(e) {
						e.preventDefault();
						show_storage_scan_dialog(frm, data);
					});
				}
				show_storage_scan_dialog(frm, data);
			} else {
				frappe.msgprint((data && data.message) || __('Error scanning storage space.'), __('Scan Error'));
				if (frm && frm.dashboard) {
					frm.dashboard.clear_headline();
				}
			}
		});

		// Check for existing cached scan results on form load
		frappe.call({
			method: 'frappe_s3_attachment.controller.get_cached_scan_result',
			callback: function(r) {
				if (r.message && r.message.status === 'success' && r.message.total_mb > 0) {
					var cached = r.message;
					if (frm && frm.dashboard) {
						frm.dashboard.set_headline(
							__('Last Storage Scan: <b>{0} MB</b> reclaimable. <button class="btn btn-xs btn-default ml-2 btn-cached-reclaim">View Results</button>', [cached.total_mb]),
							'blue'
						);
						frm.$wrapper.find('.btn-cached-reclaim').off('click').on('click', function(e) {
							e.preventDefault();
							show_storage_scan_dialog(frm, cached);
						});
					}
				}
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
							var doc_name = r.message.migration_doc;
							var msg = doc_name
								? __('File migration enqueued. Tracking in S3 Migration: {0}', ['<a href="/app/s3-migration/' + doc_name + '"><b>' + doc_name + '</b></a>'])
								: __('File migration has been enqueued in the background.');
							frappe.show_alert({
								message: msg,
								indicator: 'green'
							}, 10);
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
							var doc_name = r.message.migration_doc;
							var msg = doc_name
								? __('File restore enqueued. Tracking in S3 Migration: {0}', ['<a href="/app/s3-migration/' + doc_name + '"><b>' + doc_name + '</b></a>'])
								: __('File restore has been enqueued in the background.');
							frappe.show_alert({
								message: msg,
								indicator: 'green'
							}, 10);
						} else {
							frappe.msgprint(__('Unable to queue restore job. Please check error logs.'));
						}
					}
				});
			}
		);
	},
	scan_storage_space: function (frm) {
		var d_opts = new frappe.ui.Dialog({
			title: __('Analyze Storage & Space Savings'),
			fields: [
				{
					fieldname: 'html_info',
					fieldtype: 'HTML',
					options: '<div class="alert alert-info" style="margin-bottom:12px;font-size:12px;">' +
						__('Storage analysis scans your database, local disk, and S3 bucket to calculate safe reclaimable space. The scan runs asynchronously in the background so you can freely continue working.') +
						'</div>'
				},
				{
					fieldname: 'scope',
					fieldtype: 'Select',
					label: __('Analysis Scope'),
					options: [
						{ value: 'all', label: __('Full Storage Audit (Local Disk + AWS S3 Cloud)') },
						{ value: 'disk', label: __('Local Disk Only (Fastest — Duplicate, Orphaned & Unlinked Disk Files)') },
						{ value: 's3', label: __('S3 Cloud Storage Only (Orphaned S3 Attachments & Objects)') }
					],
					default: 'all'
				},
				{
					fieldname: 'fast_scan',
					fieldtype: 'Check',
					label: __('Fast Scan Mode (Recommended: Audits DB & Disk; skips slow raw S3 bucket pagination)'),
					default: 1
				},
				{
					fieldname: 'grace_period_days',
					fieldtype: 'Int',
					label: __('Unlinked Files Grace Period (Days)'),
					default: frm.doc.unlinked_grace_period_days || 7,
					description: __('Unattached files newer than this grace period will not be marked as abandoned.')
				}
			],
			primary_action_label: __('Start Analysis in Background'),
			primary_action: function(vals) {
				d_opts.hide();
				if (frm.dashboard) {
					frm.dashboard.set_headline(__('Storage analysis is currently running in background queue (RQ)...'), 'blue');
				}
				frappe.show_alert({
					message: __('Storage analysis enqueued in background. You will be notified automatically when ready.'),
					indicator: 'blue'
				}, 8);

				frappe.call({
					method: 'frappe_s3_attachment.controller.enqueue_scan_storage_space',
					args: {
						grace_period_days: vals.grace_period_days || 7,
						scope: vals.scope || 'all',
						fast_scan: vals.fast_scan ? 1 : 0
					},
					callback: function(r) {
						if (!r.message || r.message.status !== 'enqueued') {
							if (frm.dashboard) {
								frm.dashboard.clear_headline();
							}
							frappe.msgprint(__('Unable to enqueue storage scan. Please check error logs.'));
						}
					}
				});
			}
		});
		d_opts.show();
	},
	view_last_scan: function (frm) {
		frappe.call({
			method: 'frappe_s3_attachment.controller.get_cached_scan_result',
			freeze: true,
			freeze_message: __('Fetching latest storage scan report...'),
			callback: function(r) {
				if (r.message && r.message.status === 'success') {
					show_storage_scan_dialog(frm, r.message);
				} else {
					frappe.msgprint({
						title: __('No Scan Report Found'),
						indicator: 'orange',
						message: __('No cached scan results available. Click <b>"Scan & Reclaim Storage Space"</b> to initiate an analysis.')
					});
				}
			}
		});
	}
});

function show_storage_scan_dialog(frm, scan_data) {
	var disk = scan_data.disk_summary || {};
	var s3 = scan_data.s3_summary || {};
	var total_mb = scan_data.total_mb || 0;
	var total_files = scan_data.total_files || 0;
	var disk_mb = disk.total_mb || 0;
	var s3_mb = s3.total_mb || 0;
	var scan_time = scan_data.scan_time || __('Recent');
	var scope = scan_data.scope || 'all';

	var dup_files = disk.duplicate_local_files || { count: 0, mb: 0, samples: [] };
	var orp_disk = disk.orphaned_disk_attachments || { count: 0, mb: 0, samples: [] };
	var unl_disk = disk.unlinked_disk_files || { count: 0, mb: 0, samples: [] };
	var unref_disk = disk.unreferenced_disk_files || { count: 0, mb: 0, samples: [] };

	var orp_s3 = s3.orphaned_s3_attachments || { count: 0, mb: 0, samples: [] };
	var unl_s3 = s3.unlinked_s3_files || { count: 0, mb: 0, samples: [] };
	var unref_s3 = s3.unreferenced_s3_objects || { count: 0, mb: 0, samples: [] };

	function round_mb(val) {
		return Math.round((val || 0) * 100) / 100;
	}

	var hero_html = '<div style="background:var(--bg-subtle, #f8f9fa); border: 1px solid var(--border-color, #d1d8dd); border-radius: 8px; padding: 14px 18px; margin-bottom: 16px;">' +
		'<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 10px;">' +
			'<div>' +
				'<div style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted, #6c757d); font-weight: 600;">' + __('Total Reclaimable Storage') + '</div>' +
				'<div style="font-size: 22px; font-weight: 700; color: var(--text-color, #1f272e);">' + total_mb + ' MB <span style="font-size: 13px; font-weight: 400; color: var(--text-muted, #6c757d);">(' + total_files + ' ' + __('files / objects') + ')</span></div>' +
			'</div>' +
			'<div style="text-align:right; font-size: 11px; color: var(--text-muted, #6c757d);">' +
				'<div>' + __('Audited: {0}', [scan_time]) + '</div>' +
				'<div>' + __('Scope: {0} | Fast Scan: {1}', [scope.toUpperCase(), scan_data.fast_scan ? __('Yes') : __('Deep')]) + '</div>' +
			'</div>' +
		'</div>' +
		'<div style="display:flex; gap: 12px; font-size: 12px;">' +
			'<div style="flex:1; background: #e8f4fd; border-left: 3px solid #1b84ff; padding: 6px 10px; border-radius: 4px;">' +
				'<b>' + __('Local Disk Savings:') + '</b> ' + disk_mb + ' MB (' + (disk.total_files || 0) + ' files)' +
			'</div>' +
			'<div style="flex:1; background: #e6f8ec; border-left: 3px solid #17c653; padding: 6px 10px; border-radius: 4px;">' +
				'<b>' + __('S3 Cloud Savings:') + '</b> ' + s3_mb + ' MB (' + (s3.total_files || 0) + ' objects)' +
			'</div>' +
		'</div>' +
	'</div>';

	var d = new frappe.ui.Dialog({
		title: __('Storage Reclamation & Space Savings Hub'),
		fields: [
			{
				fieldname: 'html_hero',
				fieldtype: 'HTML',
				options: hero_html
			},
			{
				fieldname: 'sec_safe',
				fieldtype: 'Section Break',
				label: __('🟢 Zero Risk — Safe to Reclaim Immediately ({0} MB)', [dup_files.mb])
			},
			{
				fieldname: 'duplicate_local_files',
				fieldtype: 'Check',
				label: __('Redundant Local Files (Stored on S3, redundant copy on disk): {0} files ({1} MB)', [dup_files.count, dup_files.mb]),
				default: dup_files.count > 0 ? 1 : 0,
				description: __('Safe: S3 object verified on cloud. Removing local copy frees server disk space with 0% risk of data loss.')
			},
			{
				fieldname: 'sec_caution',
				fieldtype: 'Section Break',
				label: __('🟡 Caution — Unlinked & Orphaned Attachments ({0} MB)', [
					round_mb(orp_disk.mb + unl_disk.mb + orp_s3.mb + unl_s3.mb)
				])
			},
			{
				fieldname: 'orphaned_disk_attachments',
				fieldtype: 'Check',
				label: __('Orphaned Disk Files (Parent DocType was deleted): {0} files ({1} MB)', [orp_disk.count, orp_disk.mb]),
				default: orp_disk.count > 0 ? 1 : 0
			},
			{
				fieldname: 'unlinked_disk_files',
				fieldtype: 'Check',
				label: __('Abandoned Unlinked Disk Files (> {0} days old): {1} files ({2} MB)', [frm.doc.unlinked_grace_period_days || 7, unl_disk.count, unl_disk.mb]),
				default: unl_disk.count > 0 ? 1 : 0
			},
			{
				fieldname: 'orphaned_s3_attachments',
				fieldtype: 'Check',
				label: __('Orphaned S3 Cloud Objects (Parent DocType was deleted): {0} objects ({1} MB)', [orp_s3.count, orp_s3.mb]),
				default: orp_s3.count > 0 ? 1 : 0
			},
			{
				fieldname: 'unlinked_s3_files',
				fieldtype: 'Check',
				label: __('Abandoned Unlinked S3 Objects (> {0} days old): {1} objects ({2} MB)', [frm.doc.unlinked_grace_period_days || 7, unl_s3.count, unl_s3.mb]),
				default: unl_s3.count > 0 ? 1 : 0
			},
			{
				fieldname: 'sec_high_risk',
				fieldtype: 'Section Break',
				label: __('🔴 High Caution — Unreferenced Storage ({0} MB)', [
					round_mb(unref_disk.mb + unref_s3.mb)
				])
			},
			{
				fieldname: 'unreferenced_disk_files',
				fieldtype: 'Check',
				label: __('Unreferenced Physical Disk Files (Files on server disk with no DB record): {0} files ({1} MB)', [unref_disk.count, unref_disk.mb]),
				default: 0,
				description: __('Caution: These files exist in public/private folders without any matching File record in the database.')
			},
			{
				fieldname: 'unreferenced_s3_objects',
				fieldtype: 'Check',
				label: __('Unreferenced S3 Bucket Objects (Objects in S3 with no DB record): {0} objects ({1} MB)', [unref_s3.count, unref_s3.mb]),
				default: 0,
				description: __('Caution: Raw S3 bucket objects that do not map to any active File or S3 File doctype.')
			}
		],
		primary_action_label: __('Reclaim Selected Space'),
		primary_action: function () {
			execute_reclamation(false);
		}
	});

	function get_selected_categories() {
		var vals = d.get_values() || {};
		var selected = [];
		if (vals.duplicate_local_files) selected.push('duplicate_local_files');
		if (vals.orphaned_disk_attachments) selected.push('orphaned_disk_attachments');
		if (vals.unlinked_disk_files) selected.push('unlinked_disk_files');
		if (vals.unreferenced_disk_files) selected.push('unreferenced_disk_files');
		if (vals.orphaned_s3_attachments) selected.push('orphaned_s3_attachments');
		if (vals.unlinked_s3_files) selected.push('unlinked_s3_files');
		if (vals.unreferenced_s3_objects) selected.push('unreferenced_s3_objects');
		return selected;
	}

	function execute_reclamation(is_dry_run) {
		var selected = get_selected_categories();
		if (selected.length === 0) {
			frappe.msgprint(__('Please select at least one storage category to reclaim.'));
			return;
		}

		var confirm_text = is_dry_run
			? __('Simulate storage cleanup for {0} selected categories? (No files will be deleted).', [selected.length])
			: __('Are you sure you want to permanently reclaim storage for {0} selected categories? This cleanup will run in the background.', [selected.length]);

		frappe.confirm(confirm_text, function () {
			d.hide();
			frappe.call({
				method: 'frappe_s3_attachment.controller.reclaim_storage_space',
				args: {
					target: 'all',
					categories: selected,
					grace_period_days: frm.doc.unlinked_grace_period_days || 7,
					dry_run: is_dry_run ? 1 : 0
				},
				freeze: true,
				freeze_message: is_dry_run ? __('Initiating Dry Run simulation...') : __('Queueing storage reclamation...'),
				callback: function (resp) {
					if (resp.message && resp.message.status === 'enqueued') {
						var doc_name = resp.message.migration_doc;
						var action_label = is_dry_run ? __('Dry Run Simulation') : __('Storage Reclamation');
						var msg = doc_name
							? __('{0} enqueued in background. Tracking in S3 Migration: {1}', [action_label, '<a href="/app/s3-migration/' + doc_name + '"><b>' + doc_name + '</b></a>'])
							: __('{0} has been enqueued in the background.', [action_label]);
						frappe.show_alert({ message: msg, indicator: 'green' }, 10);
					} else {
						frappe.msgprint(__('Unable to queue cleanup job. Please check error logs.'));
					}
				}
			});
		});
	}

	d.set_secondary_action_label(__('Dry Run (Simulate)'));
	d.set_secondary_action(function () {
		execute_reclamation(true);
	});

	d.add_custom_action(__('Preview Sample Files'), function () {
		show_preview_samples_modal(disk, s3);
	});

	d.show();
}

function show_preview_samples_modal(disk, s3) {
	var categories = [
		{ label: __('Duplicate Local Files'), data: (disk.duplicate_local_files || {}).samples },
		{ label: __('Orphaned Disk Files'), data: (disk.orphaned_disk_attachments || {}).samples },
		{ label: __('Unlinked Disk Files'), data: (disk.unlinked_disk_files || {}).samples },
		{ label: __('Unreferenced Disk Files'), data: (disk.unreferenced_disk_files || {}).samples },
		{ label: __('Orphaned S3 Objects'), data: (s3.orphaned_s3_attachments || {}).samples },
		{ label: __('Unlinked S3 Objects'), data: (s3.unlinked_s3_files || {}).samples },
		{ label: __('Unreferenced S3 Objects'), data: (s3.unreferenced_s3_objects || {}).samples }
	];

	var preview_html = '<div style="max-height: 450px; overflow-y: auto;">';
	var has_any = false;

	categories.forEach(function(cat) {
		if (cat.data && cat.data.length > 0) {
			has_any = true;
			preview_html += '<h6 style="margin-top: 14px; margin-bottom: 6px; font-weight: 700; color: var(--text-color, #1f272e);">' + cat.label + ' (' + cat.data.length + ' sample items)</h6>';
			preview_html += '<table class="table table-bordered table-condensed" style="font-size: 11px; margin-bottom: 12px;">';
			preview_html += '<thead><tr class="text-muted"><th>' + __('File / Key') + '</th><th>' + __('Size (MB)') + '</th><th>' + __('Details') + '</th></tr></thead><tbody>';
			cat.data.forEach(function(row) {
				var display_name = row.file_name || row.name || row.file_url;
				preview_html += '<tr>' +
					'<td style="word-break: break-all; max-width: 250px;">' + frappe.utils.escape_html(display_name) + '</td>' +
					'<td style="white-space: nowrap;">' + (row.size_mb || 0) + ' MB</td>' +
					'<td>' + frappe.utils.escape_html(row.info || '-') + '</td>' +
				'</tr>';
			});
			preview_html += '</tbody></table>';
		}
	});

	if (!has_any) {
		preview_html += '<div class="text-muted text-center" style="padding: 24px;">' + __('No sample files found for the current scan.') + '</div>';
	}
	preview_html += '</div>';

	var prev_d = new frappe.ui.Dialog({
		title: __('Candidate File Previews (Samples)'),
		fields: [
			{
				fieldname: 'samples_html',
				fieldtype: 'HTML',
				options: preview_html
			}
		],
		primary_action_label: __('Close'),
		primary_action: function () {
			prev_d.hide();
		}
	});
	prev_d.show();
}



