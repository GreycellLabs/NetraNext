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
        if not self.central_server_url:
            self.central_server_url = "https://netranext.m.frappe.cloud"
        self.validate_connection_details()
        self.prevent_central_server_url_change()

    def validate_connection_details(self):
        if not self.api_key:
            frappe.throw(_("API Key is required"))

        if not self.central_server_url:
            frappe.throw(_("Central Server URL is required"))

    def prevent_central_server_url_change(self):
        # Prevent editing Central Server URL once it has been saved
        db_val = frappe.db.get_single_value("NetraNext Settings", "central_server_url")
        if db_val and self.central_server_url != db_val:
            frappe.throw(_("Central Server URL is fixed and cannot be modified once set."))

    def test_connection(self):
        """Test connection to central NetraNext server"""
        try:
            if not self.central_server_url:
                self.central_server_url = "https://netranext.m.frappe.cloud"
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
                        data = msg.get("data", {})
                        
                        self.db_set("connection_status", "Connected")
                        if data.get("tenant_id"):
                            self.db_set("tenant_id", data.get("tenant_id"))
                        if data.get("status"):
                            self.db_set("status", data.get("status"))
                        if data.get("tenant_name"):
                            self.db_set("tenant_name", data.get("tenant_name"))
                            
                        frappe.db.commit()
                        frappe.msgprint(_("Connection successful!"))
                        return True
                    else:
                        err = msg.get("message", "Unknown error from server")
                        self.db_set("connection_status", "Error")
                        frappe.db.commit()
                        
                        if "invalid" in err.lower() or "expired" in err.lower() or "token" in err.lower():
                            frappe.throw(_("Wrong API Key. Please contact support."))
                        else:
                            frappe.throw(_("{0}. Please contact support.").format(err))
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

    def reveal_api_key(self):
        """Reveal the integration token (decrypted api_key)"""
        if "System Manager" not in frappe.get_roles():
            frappe.throw(_("Not authorized to reveal integration token"))
        return self.get_password("api_key")

    def on_update(self):
        """Sync status changes to orchestrator if status has changed"""
        if self.has_value_changed("status"):
            self.sync_status_to_orchestrator()

    def sync_status_to_orchestrator(self):
        """Send status update payload to Central Orchestrator"""
        if not self.central_server_url or not self.api_key:
            return

        import requests
        try:
            url = f"{self.central_server_url.rstrip('/')}/api/method/netranext.apis.v1.tenant_onboarding.update_tenant_status_from_client"
            headers = {
                "X-NetraNext-Token": self.get_password("api_key"),
                "Content-Type": "application/json"
            }
            payload = {
                "status": self.status
            }
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code != 200:
                frappe.logger().warning(
                    f"Failed to sync status change to orchestrator. HTTP Status: {response.status_code}"
                )
        except Exception as e:
            frappe.logger().warning(
                f"Failed to sync status change to orchestrator: {str(e)}"
            )


@frappe.whitelist()
def test_connection():
    """Global endpoint to test connection without passing document from client"""
    settings = frappe.get_single("NetraNext Settings")
    return settings.test_connection()


@frappe.whitelist()
def reveal_api_key():
    """Global endpoint to reveal API key without passing document from client"""
    settings = frappe.get_single("NetraNext Settings")
    return settings.reveal_api_key()