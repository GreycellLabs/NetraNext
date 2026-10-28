"""Install/migrate missing NetraNext pages and desktop navigation.

Existing records and access settings belong to the site administrator.
"""
import frappe

from netranext_client.netranext.desktop_setup import ensure_desktop_setup


def execute():
    # Define NetraNext pages
    netranext_pages = [
        {
            "doctype": "Page",
            "name": "netranext-dashboard",
            "page_name": "netranext-dashboard",
            "module": "NetraNext",
            "standard": "Yes",
            "system_page": 1,
            "title": "NetraNext Dashboard",
            "icon": "fa-dashboard"
        },
        {
            "doctype": "Page",
            "name": "netranext-live-tracking",
            "page_name": "netranext-live-tracking",
            "module": "NetraNext",
            "standard": "Yes",
            "system_page": 1,
            "title": "Live Tracking",
            "icon": "fa-map-marker"
        },
        {
            "doctype": "Page",
            "name": "netranext-trip-history",
            "page_name": "netranext-trip-history",
            "module": "NetraNext",
            "standard": "Yes",
            "system_page": 1,
            "title": "Trip History",
            "icon": "fa-history"
        },
        {
            "doctype": "Page",
            "name": "netranext-trip-details",
            "page_name": "netranext-trip-details",
            "module": "NetraNext",
            "standard": "Yes",
            "system_page": 1,
            "title": "Trip Details",
            "icon": "fa-info-circle"
        },
        {
            "doctype": "Page",
            "name": "netranext-expense-claims",
            "page_name": "netranext-expense-claims",
            "module": "NetraNext",
            "standard": "Yes",
            "system_page": 1,
            "title": "Expense Claim List",
            "icon": "fa-money"
        }
    ]


    roles = ["System Manager", "HR Manager", "HR User", "Employee", "All"]
    for data in netranext_pages:
        if frappe.db.exists("Page", data["name"]):
            continue
        doc = frappe.get_doc(data)
        doc.flags.do_not_update_json = True
        for role in roles:
            if frappe.db.exists("Role", role):
                doc.append("roles", {"role": role})
        # Keep existing page creation compatibility (standard Page registration).
        previous = getattr(frappe.conf, "developer_mode", 0)
        frappe.conf.developer_mode = 1
        try:
            doc.insert(ignore_permissions=True)
        finally:
            frappe.conf.developer_mode = previous
        if doc.name != data["name"]:
            # Older Frappe Page autonaming truncates long names. Only rename the
            # page we just created, never an existing administrator record.
            frappe.rename_doc("Page", doc.name, data["name"], force=True)

    result = ensure_desktop_setup()
    frappe.clear_cache()
    return result
