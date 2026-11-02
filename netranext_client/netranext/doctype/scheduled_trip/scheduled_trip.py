import frappe
from frappe.model.document import Document


class ScheduledTrip(Document):
    def after_insert(self):
        self.manage_todo()

    def on_update(self):
        self.manage_todo()

    def manage_todo(self):
        """Keep one current assignment; use ORM saves so ToDo hooks run."""
        user_id = frappe.db.get_value("Employee", self.employee, "user_id") if self.employee else None
        todos = frappe.get_all(
            "ToDo",
            filters={"reference_type": "Scheduled Trip", "reference_name": self.name},
            fields=["name", "allocated_to", "status"],
            order_by="creation asc",
        )
        current = None
        # Prefer the already-open row over historical closed duplicates.
        for row in sorted(todos, key=lambda row: row.status != "Open"):
            # Reassignment must retire the previous employee's task. Terminal
            # trips close ALL assignments, including legacy duplicate rows.
            keep = (
                self.status in ("Scheduled", "In Progress")
                and user_id
                and row.allocated_to == user_id
                and current is None
            )
            if keep:
                current = row
            elif row.status == "Open":
                todo = frappe.get_doc("ToDo", row.name)
                todo.status = "Closed"
                todo.save(ignore_permissions=True)

        # Starting a trip must not create/reopen an assignment. Scheduling
        # again does reopen it and emits a fresh assignment generation.
        if self.status != "Scheduled" or not user_id:
            return
        if current:
            if current.status != "Open":
                todo = frappe.get_doc("ToDo", current.name)
                todo.status = "Open"
                todo.save(ignore_permissions=True)
            return

        frappe.get_doc({
            "doctype": "ToDo",
            "allocated_to": user_id,
            "assigned_by": frappe.session.user,
            "reference_type": "Scheduled Trip",
            "reference_name": self.name,
            "description": f"Upcoming Trip scheduled to start at {self.scheduled_start_time}",
            "status": "Open",
            "date": frappe.utils.getdate(self.scheduled_start_time) if self.scheduled_start_time else frappe.utils.today(),
        }).insert(ignore_permissions=True)
