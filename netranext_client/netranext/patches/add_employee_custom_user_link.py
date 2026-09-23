import frappe

def execute():
    """
    Remove custom_user_link custom field from Employee DocType if present,
    since user links are managed in NetraNext User Mapping DocType.
    """
    if frappe.db.exists("Custom Field", "Employee-custom_user_link"):
        try:
            frappe.delete_doc("Custom Field", "Employee-custom_user_link", ignore_permissions=True)
            frappe.db.commit()
            frappe.logger().info("Successfully removed custom_user_link field from Employee DocType.")
        except Exception as e:
            frappe.logger().error(f"Error removing custom_user_link field from Employee DocType: {e}")

