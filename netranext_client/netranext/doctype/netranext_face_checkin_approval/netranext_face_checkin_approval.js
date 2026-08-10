// Copyright (c) 2026, NetraNext and contributors
// For license information, please see license.txt

frappe.ui.form.on('NetraNext Face Checkin Approval', {
	refresh: function(frm) {
		if (frm.doc.status === 'Pending') {
			frm.add_custom_button(__('Approve'), function() {
				frappe.confirm('Are you sure you want to approve this attendance check-in?', function() {
					frm.call('approve').then(r => {
						frm.reload_doc();
					});
				});
			}).addClass('btn-primary');

			frm.add_custom_button(__('Reject'), function() {
				frappe.confirm('Are you sure you want to reject this attendance check-in?', function() {
					frm.call('reject').then(r => {
						frm.reload_doc();
					});
				});
			}).addClass('btn-danger');
		}
	}
});
