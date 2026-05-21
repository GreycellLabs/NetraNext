// Copyright (c) 2024, NetraNext and contributors
// For license information, please see license.txt

frappe.ui.form.on('NetraNext Settings', {
    refresh: function(frm) {
        // If no token is entered, show a helpful message
        if (!frm.doc.api_key) {
            frm.dashboard.set_headline(__('Please enter your Integration Token (Setup Token) provided via email to activate this client bench.'));
        } else {
            frm.add_custom_button(__('Reveal Token'), function() {
                frappe.call({
                    method: 'reveal_api_key',
                    doc: frm.doc,
                    callback: function(r) {
                        if (r.message) {
                            let d = new frappe.ui.Dialog({
                                title: __('Integration Token'),
                                fields: [
                                    {
                                        label: __('Token'),
                                        fieldname: 'token_display',
                                        fieldtype: 'Data',
                                        read_only: 1,
                                        default: r.message
                                    }
                                ],
                                primary_action_label: __('Copy to Clipboard'),
                                primary_action: function() {
                                    frappe.utils.copy_to_clipboard(r.message);
                                    d.hide();
                                    frappe.show_alert({
                                        message: __('Integration Token copied to clipboard'),
                                        indicator: 'green'
                                    });
                                }
                            });
                            d.show();
                        }
                    }
                });
            });
        }
    },

    after_save: function(frm) {
        // After saving, if token exists, automatically test connection
        if (frm.doc.api_key) {
            frappe.call({
                doc: frm.doc,
                method: "test_connection",
                freeze: true,
                freeze_message: __('Verifying connection with Central Orchestrator...'),
                callback: function(r) {
                    frm.reload_doc();
                    if (!r.exc) {
                        frappe.show_alert({
                            message: __('Connection verified successfully!'),
                            indicator: 'green'
                        });
                    }
                },
                error: function(r) {
                    frm.reload_doc();
                }
            });
        }
    }
});
