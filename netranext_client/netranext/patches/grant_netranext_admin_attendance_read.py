"""Let NetraNext Admin read every employee's attendance (read-only).

Employee Checkin and Employee belong to HRMS/ERPNext, so their permissions
are extended through Frappe's own Custom DocPerm helpers (which first copy
the standard rules, keeping every existing role's access). Only read,
report and export are granted: no write/create/delete on HR records.
Runs once; later changes made in Role Permission Manager are kept.
"""
import frappe
from frappe.permissions import add_permission, update_permission_property

from netranext_client.netranext.patches.create_netranext_admin_role import ROLE, execute as ensure_role

DOCTYPES = ("Employee Checkin", "Employee")


def execute():
    ensure_role()
    for doctype in DOCTYPES:
        if not frappe.db.exists("DocType", doctype):
            continue
        if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": ROLE, "permlevel": 0, "if_owner": 0}):
            continue
        add_permission(doctype, ROLE, 0, "read")
        for ptype in ("report", "export"):
            update_permission_property(doctype, ROLE, 0, ptype, 1)
