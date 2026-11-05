"""Journey visibility for Desk, custom pages and authenticated mobile proxies.

Ownership means Employee.user_id, never the Journey creator or a caller's
employee/user filter. Manager roles bypass only this ownership constraint;
Frappe's configured role and User Permissions still apply.
"""
import frappe

JOURNEY = "NetraNext Journey"
MANAGER_ROLES = frozenset({"System Manager", "HR Manager", "HR User"})


def _user(user=None):
    return user or frappe.session.user


def is_trip_manager(user=None):
    user = _user(user)
    return user == "Administrator" or bool(MANAGER_ROLES.intersection(frappe.get_roles(user)))


def require_reader(user=None):
    user = _user(user)
    if not user or user == "Guest":
        frappe.throw("You are not permitted to access trip data.", frappe.PermissionError)
    frappe.has_permission(JOURNEY, "read", user=user, throw=True)
    return user


def get_permission_query_conditions(user=None):
    user = _user(user)
    if not user or user == "Guest":
        return "1=0"
    if is_trip_manager(user):
        return ""
    return ("`tabNetraNext Journey`.`employee` IN "
            "(SELECT name FROM `tabEmployee` WHERE user_id = "
            + frappe.db.escape(user) + ")")


def has_permission(doc, user=None, ptype=None, debug=False):
    """A veto only: never grant privileges absent from standard permissions."""
    user = _user(user)
    if not user or user == "Guest":
        return False
    if is_trip_manager(user):
        return None
    if not doc.employee or not frappe.db.exists("Employee", {"name": doc.employee, "user_id": user}):
        return False
    return None


def check_trip_read(doc, user=None):
    user = require_reader(user)
    if has_permission(doc, user) is False:
        frappe.throw("You are not permitted to access this trip.", frappe.PermissionError)
    frappe.has_permission(JOURNEY, "read", doc=doc, user=user, throw=True)


def scoped_filters(filters=None, user=None):
    """AND ownership with caller filters, including OR searches and shares."""
    user = require_reader(user)
    if isinstance(filters, dict):
        result = [[key, *value] if isinstance(value, (list, tuple)) else [key, "=", value]
                  for key, value in filters.items()]
    else:
        result = list(filters or [])
    if not is_trip_manager(user):
        employees = frappe.get_all("Employee", filters={"user_id": user}, pluck="name")
        result.append(["employee", "in", employees] if employees else ["name", "=", ""])
    return result


def integration_reader(user):
    """Called ONLY after validating the central server integration token."""
    if not user or user == "Guest" or not frappe.db.get_value("User", user, "enabled"):
        frappe.throw("An enabled authenticated trip reader is required.", frappe.PermissionError)
    return require_reader(user)


def get_trip_list(doctype, user=None, **kwargs):
    """Bind the proxy reader before Frappe's initial query permission check.

    Passing only execute(user=...) is too late on this Frappe version:
    check_read_permission runs before execute updates self.user. Integration
    requests normally have a Guest session, so construct the query as the
    authenticated reader without changing the request's session user.
    """
    from frappe.model.db_query import DatabaseQuery
    if doctype != JOURNEY:
        raise ValueError("This query is only for Journey records")
    user = require_reader(user)
    return DatabaseQuery(JOURNEY, user=user).execute(user=user, **kwargs)
