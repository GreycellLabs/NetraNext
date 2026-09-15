import frappe

def execute():
    """
    Patch to register NetraNext custom pages in the database
    This ensures the pages show up in the Page list and are accessible
    """
    # Delete the old netranext-mapview page if it exists
    if frappe.db.exists("Page", "netranext-mapview"):
        frappe.delete_doc("Page", "netranext-mapview", ignore_permissions=True)
        frappe.db.commit()

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
        }
    ]

    # Define roles to assign
    #
    # "All" is REQUIRED: every Frappe user automatically holds the built-in
    # "All" role, and the NetraNext workspace only appears in a user's sidebar
    # if the user can access at least one Page/DocType of the NetraNext
    # module (frappe.desk.desktop.Workspace raises PermissionError otherwise,
    # which the sidebar silently swallows). Without "All" on the pages, users
    # holding no HR/Employee role lose the whole workspace after login.
    # Keep this list in sync with the page JSON files (they also ship "All").
    roles_to_assign = ["System Manager", "HR Manager", "HR User", "All"]

    for page_data in netranext_pages:
        page_name = page_data["name"]

        # Check if page exists
        if frappe.db.exists("Page", page_name):
            # Update existing page
            frappe.db.set_value("Page", page_name, {
                "system_page": 1,
                "standard": "Yes",
                "module": "NetraNext",
                "title": page_data["title"],
                "icon": page_data["icon"]
            })

            # Get the page doc
            page_doc = frappe.get_doc("Page", page_name)

            # Clear existing roles
            page_doc.roles = []

            # Add roles
            for role in roles_to_assign:
                page_doc.append("roles", {
                    "role": role
                })

            page_doc.save(ignore_permissions=True)
            frappe.db.commit()

            print(f"✅ Updated page: {page_name}")

        else:
            # Create new page
            page_doc = frappe.get_doc(page_data)

            # Add roles
            for role in roles_to_assign:
                page_doc.append("roles", {
                    "role": role
                })

            page_doc.insert(ignore_permissions=True)
            frappe.db.commit()

            print(f"✅ Created page: {page_name}")

    # Register/Update NetraNext Workspace
    workspace_name = "NetraNext"
    if frappe.db.exists("Workspace", workspace_name):
        ws_doc = frappe.get_doc("Workspace", workspace_name)
        ws_doc.public = 1
        ws_doc.is_hidden = 0
        ws_doc.sequence_id = 1.0
        ws_doc.roles = []
        for role in roles_to_assign:
            ws_doc.append("roles", {"role": role})
        ws_doc.save(ignore_permissions=True)
        frappe.db.commit()
        print(f"✅ Updated workspace permissions and sequence for: {workspace_name}")
    else:
        print(f"⚠️ Workspace {workspace_name} not found in DB, standard import will create it on migrate.")

    # Ensure Installed Application record exists with has_setup_wizard=0 so non-System Managers see NetraNext on Desk
    if frappe.db.exists("Installed Application", "netranext_client"):
        frappe.db.set_value("Installed Application", "netranext_client", {
            "has_setup_wizard": 0,
            "is_setup_complete": 1
        })
        frappe.db.commit()
    else:
        try:
            frappe.get_doc({
                "doctype": "Installed Application",
                "app_name": "netranext_client",
                "app_title": "NetraNext Client",
                "has_setup_wizard": 0,
                "is_setup_complete": 1
            }).insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            pass

    # Set NetraNext as default_workspace for active System Users if unset
    users_updated = 0
    system_users = frappe.get_all("User", filters={"user_type": "System User", "enabled": 1}, pluck="name")
    for user_email in system_users:
        user_doc = frappe.get_doc("User", user_email)
        # Ensure NetraNext is not in block_modules
        if hasattr(user_doc, "block_modules") and user_doc.block_modules:
            user_doc.block_modules = [m for m in user_doc.block_modules if m.module != "NetraNext"]
        if not user_doc.default_workspace:
            user_doc.default_workspace = "NetraNext"
            users_updated += 1
        user_doc.save(ignore_permissions=True)
    frappe.clear_cache()
    print("🚀 NetraNext pages and workspace registration completed!")

