import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def execute():
    """
    Add custom_user_link custom field to Employee DocType on tenant bench
    so that admins can enter per-employee dynamic URLs in Frappe Desk.
    """
    custom_fields = {
        "Employee": [
            {
                "fieldname": "custom_user_link",
                "label": "Custom User Link",
                "fieldtype": "Data",
                "insert_after": "user_id",
                "description": "Dynamic per-employee link displayed on the mobile app dashboard",
            }
        ]
    }
    
    try:
        create_custom_fields(custom_fields, ignore_validate=True)
        frappe.db.commit()
        frappe.logger().info("Successfully created custom_user_link field on Employee DocType in netranext_client.")
    except Exception as e:
        frappe.logger().error(f"Error creating custom_user_link field on Employee DocType in netranext_client: {e}")
