// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on('S3 Migration', {
	refresh: function(frm) {
		frappe.realtime.off('s3_migration_progress');
		frappe.realtime.on('s3_migration_progress', function(data) {
			if (data && data.migration_doc === frm.doc.name) {
				frm.doc.current_phase = data.current_phase || '';
				frm.doc.current_file = data.current_file || '';
				frm.doc.total_files_scanned = data.total_files_scanned || 0;
				frm.doc.successful_files = data.successful_files || 0;
				frm.doc.skipped_files = data.skipped_files || 0;
				frm.doc.failed_files = data.failed_files || 0;
				frm.doc.progress_percentage = data.progress_percentage || 0;
				frm.doc.last_heartbeat = data.last_heartbeat || '';

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

				if (frm.dashboard) {
					frm.dashboard.set_headline(
						__('Job is running ({0}%): {1} - {2}', [
							data.progress_percentage || 0,
							data.current_phase || __('In Progress'),
							data.current_file || ''
						]),
						'blue'
					);
				}
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

		frappe.realtime.off('s3_cleanup_complete');
		frappe.realtime.on('s3_cleanup_complete', function(data) {
			if (!data.migration_doc || data.migration_doc === frm.doc.name) {
				frm.reload_doc();
			}
		});

		if (frm.doc.status === 'In Progress') {
			frm.dashboard.set_headline(
				__('Job is running ({0}%): {1} - {2}', [
					frm.doc.progress_percentage || 0,
					frm.doc.current_phase || __('Initializing...'),
					frm.doc.current_file || ''
				]),
				'blue'
			);
		} else if (frm.doc.status === 'Completed') {
			frm.dashboard.set_headline(
				__('Job Completed: {0} files processed successfully.', [
					frm.doc.successful_files || 0
				]),
				'green'
			);
		} else if (frm.doc.status === 'Completed with Warnings') {
			frm.dashboard.set_headline(
				__('Job Completed with Warnings: {0} succeeded, {1} skipped, {2} failed.', [
					frm.doc.successful_files || 0,
					frm.doc.skipped_files || 0,
					frm.doc.failed_files || 0
				]),
				'orange'
			);
		} else if (frm.doc.status === 'Failed') {
			frm.dashboard.set_headline(
				__('Job Failed: {0}', [
					frm.doc.current_phase || __('Error encountered')
				]),
				'red'
			);
		}
	}
});
