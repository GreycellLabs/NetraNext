# Copyright (c) 2026, NetraNext and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class NetraNextLocationCheckinApproval(Document):
    def before_save(self):
        # Auto-set approver and date on transition from Pending
        if self.status != "Pending" and (self.is_new() or frappe.db.get_value(self.doctype, self.name, "status") == "Pending"):
            self.approver = frappe.session.user
            self.approval_date = frappe.utils.now_datetime()

    def on_update(self):
        if self.status in ["Approved", "Rejected"]:
            if self.employee_checkin:
                checkin_status = "Approved" if self.status == "Approved" else "Rejected"
                skip_auto = 0 if self.status == "Approved" else 1
                
                frappe.db.set_value("Employee Checkin", self.employee_checkin, {
                    "custom_location_status": checkin_status,
                    "skip_auto_attendance": skip_auto
                })
            
            # Close related ToDo tasks
            todos = frappe.get_all("ToDo", filters={
                "reference_type": self.doctype,
                "reference_name": self.name,
                "status": "Open"
            })
            for todo in todos:
                try:
                    todo_doc = frappe.get_doc("ToDo", todo.name)
                    todo_doc.status = "Closed"
                    todo_doc.save(ignore_permissions=True)
                except Exception as e:
                    frappe.logger().error(f"Failed to close ToDo {todo.name}: {str(e)}")
