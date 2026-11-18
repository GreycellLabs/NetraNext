"""Explain why a user can or cannot open a NetraNext Journey (read-only).

Not whitelisted: run from the bench on the affected site, e.g.

    bench --site <site> execute \\
        netranext_client.netranext.utils.permission_diagnostics.explain_trip_access \\
        --kwargs "{'user': 'someone@example.com', 'journey': 'JOURNEY-01092'}"

Prints each layer of Frappe's decision (roles -> role permissions -> NetraNext
ownership hook -> User Permissions -> final result) plus Frappe's own
permission debug log. Changes nothing.
"""
import frappe

JOURNEY = "NetraNext Journey"


def explain_trip_access(user, journey, ptype="read"):
    from frappe.permissions import get_role_permissions, has_controller_permissions, has_user_permission

    from netranext_client.netranext.utils.trip_permissions import MANAGER_ROLES, has_permission, is_trip_manager

    doc = frappe.get_doc(JOURNEY, journey)
    roles = frappe.get_roles(user)
    own_employees = frappe.get_all("Employee", filters={"user_id": user}, pluck="name")
    hook_result = has_permission(doc, user=user, ptype=ptype)

    frappe.local.permission_debug_log = []
    final = frappe.has_permission(JOURNEY, ptype, doc=doc, user=user, debug=True)
    debug_log = [line.strip() for line in (frappe.local.permission_debug_log or [])]

    report = {
        "frappe_version": frappe.__version__,
        "user": user,
        "user_enabled": bool(frappe.db.get_value("User", user, "enabled")),
        "roles": sorted(roles),
        "has_netranext_admin": "NetraNext Admin" in roles,
        "manager_roles_held": sorted(MANAGER_ROLES.intersection(roles)),
        "is_trip_manager": is_trip_manager(user),
        "linked_employees": own_employees,
        "journey": journey,
        "journey_employee_is_users_own": doc.employee in own_employees,
        "role_permissions": {k: v for k, v in get_role_permissions(JOURNEY, user=user).items()
                             if k in ("read", "write", "create", "delete") and v},
        # Must be True/False: Frappe v16 treats None as a denial.
        "ownership_hook_result": repr(hook_result),
        "controller_permission": has_controller_permissions(doc, ptype, user=user),
        "user_permission_check": has_user_permission(doc, user=user, ptype=ptype),
        "employee_link_ignores_user_permissions": bool(
            frappe.get_meta(JOURNEY).get_field("employee").ignore_user_permissions),
        "custom_docperm_rows": frappe.get_all("Custom DocPerm", filters={"parent": JOURNEY},
                                              fields=["role", "read", "write", "create", "delete"]),
        "final_has_permission": bool(final),
        "frappe_debug_log": debug_log,
    }
    for key, value in report.items():
        if key != "frappe_debug_log":
            print(f"{key:40s} {value}")
    print("frappe_debug_log:")
    for line in debug_log:
        print("   ", line)
    return report
