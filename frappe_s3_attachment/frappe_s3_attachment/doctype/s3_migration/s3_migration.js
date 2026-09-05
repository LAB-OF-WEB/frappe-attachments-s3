// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on('S3 Migration', {
	onload: function(frm) {
		if (frm.is_new()) {
			frappe.msgprint({
				title: __('Not Permitted'),
				indicator: 'red',
				message: __('Manual creation of S3 Migration records is disabled. Migrations must be initiated from S3 File Attachment settings.')
			});
			frappe.set_route('List', 'S3 Migration');
		}
	},
	refresh: function(frm) {
		if (frm.is_new()) {
			frm.disable_save();
			return;
		}
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

				set_or_update_headline(
					frm,
					__('Job is running ({0}%): {1} - {2}', [
						data.progress_percentage || 0,
						data.current_phase || __('In Progress'),
						data.current_file || ''
					]),
					'blue'
				);
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
			set_or_update_headline(
				frm,
				__('Job is running ({0}%): {1} - {2}', [
					frm.doc.progress_percentage || 0,
					frm.doc.current_phase || __('Initializing...'),
					frm.doc.current_file || ''
				]),
				'blue'
			);
		} else if (frm.doc.status === 'Completed') {
			set_or_update_headline(
				frm,
				__('Job Completed: {0} files processed successfully.', [
					frm.doc.successful_files || 0
				]),
				'green'
			);
		} else if (frm.doc.status === 'Completed with Warnings') {
			set_or_update_headline(
				frm,
				__('Job Completed with Warnings: {0} succeeded, {1} skipped, {2} failed.', [
					frm.doc.successful_files || 0,
					frm.doc.skipped_files || 0,
					frm.doc.failed_files || 0
				]),
				'orange'
			);
		} else if (frm.doc.status === 'Failed') {
			set_or_update_headline(
				frm,
				__('Job Failed: {0}', [
					frm.doc.current_phase || __('Error encountered')
				]),
				'red'
			);
		}
	}
});

function set_or_update_headline(frm, message, color) {
	color = color || 'blue';

	var $container = null;
	var $existing_alert = null;

	// Check if standard form-message exists on frm.layout or in the form wrapper
	if (frm.layout && frm.layout.message && frm.layout.message.length && frm.layout.message.is(':visible')) {
		$container = frm.layout.message;
	} else {
		var $scope = frm.wrapper ? $(frm.wrapper) : (frm.page && frm.page.wrapper ? $(frm.page.wrapper) : null);
		if ($scope && $scope.length) {
			var $found = $scope.find('.form-message:visible, .dashboard-headline:visible, .form-dashboard .alert:visible');
			if ($found.length) {
				$container = $found.first();
			}
		}
	}

	if ($container && $container.length) {
		var $children = $container.children('div');
		if ($children.length) {
			$existing_alert = $children.first();
			// Remove any subsequent alert boxes so only the first one remains
			$children.slice(1).remove();
		} else {
			$existing_alert = $container;
		}
	}

	if ($existing_alert && $existing_alert.length) {
		// Just update values of the existing first alert box
		$existing_alert.html(message);

		// Synchronize alert color class on the container
		if ($container && $container.length) {
			['blue', 'green', 'orange', 'red', 'yellow'].forEach(function(c) {
				if (c !== color) {
					$container.removeClass(c);
				}
			});
			$container.addClass(color);
			if (frm.layout) {
				frm.layout.message_color = color;
			}
		}
	} else {
		// No alert box exists yet; create the initial alert box
		if (frm.dashboard && typeof frm.dashboard.set_headline === 'function') {
			frm.dashboard.set_headline(message, color);
		} else if (frm.layout && typeof frm.layout.show_message === 'function') {
			frm.layout.show_message(message, color);
		}
	}
}
