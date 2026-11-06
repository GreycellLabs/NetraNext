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

                if self.status == "Approved":
                    # A check-in stored while outside the geofence could not
                    # start its automatic trip (approval was pending). Now that
                    # the location evidence is approved, start it; a no-op when
                    # tracking is disabled, face evidence is still pending or
                    # the trip already exists.
                    try:
                        from netranext_client.netranext.utils.attendance_journey import start_after_approval
                        start_after_approval(self.employee_checkin)
                        frappe.db.commit()
                    except Exception as trip_err:
                        frappe.log_error(
                            f"Attendance trip start after location approval failed "
                            f"for {self.employee_checkin}: {trip_err}",
                            "Attendance Trip Approval Start",
                        )

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
