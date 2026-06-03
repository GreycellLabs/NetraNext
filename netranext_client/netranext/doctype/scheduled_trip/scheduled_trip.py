import frappe
from frappe.model.document import Document

class ScheduledTrip(Document):
    def after_insert(self):
        self.manage_todo()

    def on_update(self):
        self.manage_todo()

    def manage_todo(self):
        """
        Creates or updates a ToDo record for the assigned employee based on the Scheduled Trip status.
        - Status 'Scheduled': Creates a new ToDo if none exists.
        - Status 'Completed' or 'Cancelled': Closes the existing ToDo.
        """
        # Find if a ToDo already exists for this scheduled trip
        existing_todos = frappe.get_all(
            "ToDo",
            filters={
                "reference_type": "Scheduled Trip",
                "reference_name": self.name,
                "allocated_to": frappe.db.get_value("Employee", self.employee, "user_id")
            },
            limit=1
        )

        user_id = frappe.db.get_value("Employee", self.employee, "user_id")
        
        if not user_id:
            return  # Cannot create ToDo without a linked user

        if self.status == "Scheduled":
            if not existing_todos:
                # Create a new ToDo
                todo = frappe.get_doc({
                    "doctype": "ToDo",
                    "allocated_to": user_id,
                    "reference_type": "Scheduled Trip",
                    "reference_name": self.name,
                    "description": f"Upcoming Trip scheduled to start at {self.scheduled_start_time}",
                    "status": "Open",
                    "date": self.scheduled_start_time.split(" ")[0] if self.scheduled_start_time else frappe.utils.today()
                })
                todo.insert(ignore_permissions=True)
                
        elif self.status in ["Completed", "Cancelled"]:
            if existing_todos:
                # Close the ToDo
                todo_doc = frappe.get_doc("ToDo", existing_todos[0].name)
                if todo_doc.status != "Closed":
                    todo_doc.status = "Closed"
                    todo_doc.save(ignore_permissions=True)
