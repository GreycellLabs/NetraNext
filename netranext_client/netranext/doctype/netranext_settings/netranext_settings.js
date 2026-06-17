// Copyright (c) 2024, NetraNext and contributors
// For license information, please see license.txt

frappe.ui.form.on('NetraNext Settings', {
    refresh: function(frm) {
        // Prefill the central server URL if it is empty, so it is always populated and visible
        if (!frm.doc.central_server_url && window.NetraNextConfig) {
            frm.set_value('central_server_url', window.NetraNextConfig.apiBaseUrl);
        }

        if (!frm.doc.expense_claim_type) {
            frm.set_value('expense_claim_type', 'Travel');
        }

        // If token exists, load the decrypted value into the DOM input element to enable the show/hide eye toggle
        if (frm.doc.api_key) {
            frappe.call({
                method: 'netranext_client.netranext.doctype.netranext_settings.netranext_settings.reveal_api_key',
                callback: function(r) {
                    if (r.message && frm.fields_dict.api_key && frm.fields_dict.api_key.$input) {
                        frm.fields_dict.api_key.$input.val(r.message);
                    }
                }
            });
        }

        // If no token is entered, show a helpful message
        if (!frm.doc.api_key) {
            frm.dashboard.set_headline(__('Please enter your Integration Token (Setup Token) provided via email to activate this client bench.'));
        } else {
            frm.add_custom_button(__('Reveal Token'), function() {
                frappe.call({
                    method: 'netranext_client.netranext.doctype.netranext_settings.netranext_settings.reveal_api_key',
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
                method: 'netranext_client.netranext.doctype.netranext_settings.netranext_settings.test_connection',
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
