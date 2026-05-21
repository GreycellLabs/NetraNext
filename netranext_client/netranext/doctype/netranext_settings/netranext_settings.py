# Copyright (c) 2024, NetraNext and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
import requests
import json
from datetime import datetime


class NetraNextSettings(Document):
    def validate(self):
        """Validate settings before saving"""
        self.validate_connection_details()
    def validate_connection_details(self):
        if not self.api_key:
            frappe.throw(_("Integration Token is required"))

        if not self.central_server_url:
            frappe.throw(_("Central Server URL is required"))

    @frappe.whitelist()
    def test_connection(self):
        """Test connection to central NetraNext server"""
        try:
            url = f"{self.central_server_url.rstrip('/')}/api/method/netranext.apis.v1.tenant_onboarding.activate_tenant_from_client"
            headers = {
                "X-NetraNext-Token": self.get_password("api_key")
            }

            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                try:
                    res_json = response.json()
                    msg = res_json.get("message", {})
                    if msg.get("status") == "success":
                        self.db_set("connection_status", "Connected")
                        frappe.db.commit()
                        frappe.msgprint(_("Connection successful!"))
                        return True
                    else:
                        err = msg.get("message", "Unknown error from server")
                        self.db_set("connection_status", "Error")
                        frappe.db.commit()
                        frappe.throw(_("Handshake rejected: {0}").format(err))
                except ValueError:
                    self.db_set("connection_status", "Error")
                    frappe.db.commit()
                    frappe.throw(_("Connection failed: Invalid response format from server"))
            else:
                self.db_set("connection_status", "Error")
                frappe.db.commit()
                frappe.throw(_("Connection failed with HTTP status code: {0}").format(response.status_code))

        except requests.RequestException as e:
            self.db_set("connection_status", "Disconnected")
            frappe.db.commit()
            frappe.throw(_("Connection failed: {0}").format(str(e)))

    @frappe.whitelist()
    def sync_now(self):
        """Manually trigger sync with central server"""
        try:
            from netranext_client.netranext.utils.sync_helper import manual_sync
            return manual_sync()
        except ImportError:
            frappe.msgprint(_("Sync functionality not yet implemented"))
            return None

    def get_api_credentials(self):
        """Get API credentials for making requests"""
        return {
            "integration_token": self.get_password("api_key"),
            "central_server_url": self.central_server_url
        }

    @frappe.whitelist()
    def reveal_api_key(self):
        """Reveal the integration token (decrypted api_key)"""
        if "System Manager" not in frappe.get_roles():
            frappe.throw(_("Not authorized to reveal integration token"))
        return self.get_password("api_key")