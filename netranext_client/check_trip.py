import frappe

def main():
    try:
        doc = frappe.get_doc("Scheduled Trip", "SCHED-00011")
        print(f"Scheduled Trip: {doc.name}, Status: {doc.status}, Journey Ref: {doc.journey_reference}")

        todos = frappe.get_all("ToDo", filters={"reference_name": "SCHED-00011"}, fields=["name", "status"])
        print(f"ToDos: {todos}")
    except Exception as e:
        print(f"Error: {e}")

