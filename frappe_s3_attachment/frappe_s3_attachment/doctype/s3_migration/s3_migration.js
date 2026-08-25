// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on('S3 Migration', {
	refresh: function(frm) {
		frappe.realtime.off('s3_migration_progress');
		frappe.realtime.on('s3_migration_progress', function(data) {
			if (data && data.migration_doc === frm.doc.name) {
				frm.set_value('current_phase', data.current_phase || '');
				frm.set_value('current_file', data.current_file || '');
				frm.set_value('total_files_scanned', data.total_files_scanned || 0);
				frm.set_value('successful_files', data.successful_files || 0);
				frm.set_value('skipped_files', data.skipped_files || 0);
				frm.set_value('failed_files', data.failed_files || 0);
				frm.set_value('progress_percentage', data.progress_percentage || 0);
				frm.set_value('last_heartbeat', data.last_heartbeat || '');
				frm.refresh_fields([
					'current_phase',
					'current_file',
					'total_files_scanned',
					'successful_files',
					'skipped_files',
					'failed_files',
					'progress_percentage',
					'last_heartbeat'
				]);
			}
		});

		frappe.realtime.off('s3_migration_complete');
		frappe.realtime.on('s3_migration_complete', function(data) {
			if (!data.migration_doc || data.migration_doc === frm.doc.name) {
				frm.reload_doc();
			}
		});

		frappe.realtime.off('s3_restore_complete');
		frappe.realtime.on('s3_restore_complete', function(data) {
			if (!data.migration_doc || data.migration_doc === frm.doc.name) {
				frm.reload_doc();
			}
		});

		if (frm.doc.status === 'In Progress') {
			frm.dashboard.set_headline(
				__('Job is running: {0} - {1}', [
					frm.doc.current_phase || __('Initializing...'),
					frm.doc.current_file || ''
				]),
				'blue'
			);
		}
	}
});
