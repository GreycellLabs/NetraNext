"""Make NetraNext Admin's read access to employee-owned records effective.

The DocType JSON already grants NetraNext Admin read and marks each
`employee` link `ignore_user_permissions`, so HRMS's automatic Employee User
Permission (created for every user linked to an Employee, applied to all
doctypes) does not cut an Admin who is also an employee down to their own
records. Two kinds of site configuration silently cancel that JSON on
existing tenants, and then Frappe's document-level check refuses the Admin
with "No permission for NetraNext Journey <name>":

* Custom DocPerm rows (written by Role Permission Manager or add_permission)
  replace the JSON permission rows entirely, so the NetraNext Admin row added
  later in JSON never applies.
* A Property Setter on `employee.ignore_user_permissions` (Customize Form)
  overrides the JSON flag, re-applying the Employee User Permission.

This patch only touches the NetraNext doctypes below. Employee-only users stay
limited by trip_permissions' permission_query_conditions / has_permission.
"""
import frappe
from frappe.permissions import add_permission, update_permission_property

from netranext_client.netranext.patches.create_netranext_admin_role import ROLE, execute as ensure_role
from netranext_client.netranext.utils.trip_permissions import EMPLOYEE_OWNED_DOCTYPES

RIGHTS = ("read", "write", "create", "delete", "report", "export", "print", "email", "share")


def execute():
    ensure_role()
    for doctype in EMPLOYEE_OWNED_DOCTYPES:
        if not frappe.db.exists("DocType", doctype):
            continue
        restore_employee_link_flag(doctype)
        sync_custom_admin_permission(doctype)
        frappe.clear_cache(doctype=doctype)


def restore_employee_link_flag(doctype):
    """Drop overrides of the JSON `employee.ignore_user_permissions = 1`."""
    frappe.db.delete(
        "Property Setter",
        {"doc_type": doctype, "field_name": "employee", "property": "ignore_user_permissions"},
    )


def sync_custom_admin_permission(doctype):
    """Mirror the JSON NetraNext Admin row into Custom DocPerm when the
    doctype's permissions have been customised (otherwise JSON applies)."""
    if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
        return
    standard = frappe.db.get_value(
        "DocPerm", {"parent": doctype, "role": ROLE, "permlevel": 0}, list(RIGHTS), as_dict=True
    ) or {"read": 1, "report": 1}
    # add_permission is a no-op when a level-0 row for the role already
    # exists; either way the rights below make read effective.
    add_permission(doctype, ROLE, 0, "read")
    for ptype in RIGHTS:
        if standard.get(ptype):
            update_permission_property(doctype, ROLE, 0, ptype, 1)
