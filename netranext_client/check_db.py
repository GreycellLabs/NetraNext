import frappe

def main():
    checkins = frappe.db.get_all(
        "Employee Checkin",
        fields=["name", "employee", "log_type", "time", "creation", "modified"],
        order_by="creation desc",
        limit=10
    )
    print("--- NETRANEXT.LOCAL CHECKINS ---")
    for c in checkins:
        print(f"Name: {c.name}, Employee: {c.employee}, Type: {c.log_type}, Time: {c.time}, Creation: {c.creation}")
