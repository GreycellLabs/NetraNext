import frappe
def execute():
    errors = frappe.get_all("Error Log", fields=["error", "method"], limit=1, order_by="creation desc")
    for e in errors:
        print("ERROR DUMP:")
        print(e.error)
