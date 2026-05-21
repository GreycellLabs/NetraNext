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
        self.validate_feature_flags()

    def validate_connection_details(self):
        """Validate that API credentials and server URL are provided"""
        if not self.api_key or not self.api_secret:
            frappe.throw(_("API Key and API Secret are required"))

        if not self.central_server_url:
            frappe.throw(_("Central Server URL is required"))

    def validate_feature_flags(self):
        """Validate feature flag combinations"""
        if self.enable_face_recognition and not self.enable_attendance_marking:
            frappe.msgprint(_("Warning: Face Recognition is enabled but Attendance Marking is disabled"))

    def test_connection(self):
        """Test connection to central NetraNext server"""
        try:
            url = f"{self.central_server_url.rstrip('/')}/api/method/netranext.apis.v1.auth.ping"
            headers = {
                "X-NetraNext-API-Key": self.api_key,
                "X-NetraNext-API-Secret": self.api_secret
            }

            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                self.connection_status = "Connected"
                self.save()
                frappe.msgprint(_("Connection successful!"))
                return True
            else:
                self.connection_status = "Error"
                self.save()
                frappe.throw(_("Connection failed with status code: {0}").format(response.status_code))

        except requests.RequestException as e:
            self.connection_status = "Disconnected"
            self.save()
            frappe.throw(_("Connection failed: {0}").format(str(e)))

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
            "api_key": self.api_key,
            "api_secret": self.api_secret,
            "central_server_url": self.central_server_url
        }