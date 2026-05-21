# Copyright (c) 2024, NetraNext and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
import json
from datetime import datetime


class NetraNextSyncLog(Document):
    def validate(self):
        """Validate sync log before saving"""
        self.validate_status()
        self.validate_records()

    def validate_status(self):
        """Validate status and related fields"""
        if self.status == "Completed" and self.records_failed > 0:
            self.status = "Partial Success"
        elif self.status == "Failed" and self.records_succeeded > 0:
            self.status = "Partial Success"

    def validate_records(self):
        """Validate record counts"""
        if self.records_processed < (self.records_succeeded + self.records_failed):
            frappe.throw(_("Total processed records cannot be less than succeeded + failed records"))

    def mark_completed(self, succeeded=0, failed=0):
        """Mark sync as completed"""
        self.status = "Completed" if failed == 0 else "Partial Success"
        self.records_processed = succeeded + failed
        self.records_succeeded = succeeded
        self.records_failed = failed
        self.save()

    def mark_failed(self, error_message):
        """Mark sync as failed"""
        self.status = "Failed"
        self.error_message = error_message
        self.save()

    def add_technical_details(self, url, response_code, response_time_ms):
        """Add technical details about the sync request"""
        self.request_url = url
        self.response_code = response_code
        self.response_time_ms = response_time_ms
        self.save()

    @staticmethod
    def create_sync_log(sync_type, sync_direction="Push"):
        """Create a new sync log entry"""
        log = frappe.get_doc({
            "doctype": "NetraNext Sync Log",
            "sync_type": sync_type,
            "sync_direction": sync_direction,
            "status": "Pending",
            "timestamp": datetime.now()
        })
        log.insert()
        return log

    @staticmethod
    def get_recent_logs(limit=10):
        """Get recent sync logs"""
        return frappe.get_all("NetraNext Sync Log",
            fields=["*"],
            order_by="timestamp desc",
            limit=limit
        )