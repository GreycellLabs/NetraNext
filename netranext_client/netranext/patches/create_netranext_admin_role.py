"""Create the NetraNext Admin role on the tenant bench.

Runs before DocType sync because NetraNext DocTypes grant this role
permissions. The role used to exist only on the central server, so tenant
users given it (manually) were treated like ordinary users and refused.
"""
import frappe

ROLE = "NetraNext Admin"


def execute():
    if not frappe.db.exists("Role", ROLE):
        frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1}).insert()
