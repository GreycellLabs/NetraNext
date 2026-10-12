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

    # Define roles to assign
    #
    # "All" is REQUIRED: every Frappe user automatically holds the built-in
    # "All" role, and the NetraNext workspace only appears in a user's sidebar
    # if the user can access at least one Page/DocType of the NetraNext
    # module (frappe.desk.desktop.Workspace raises PermissionError otherwise,
    # which the sidebar silently swallows). Without "All" on the pages, users
    # holding no HR/Employee role lose the whole workspace after login.
    # Keep this list in sync with the page JSON files (they also ship "All").
    roles_to_assign = ["System Manager", "HR Manager", "HR User", "Employee", "All"]

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

            orig_dev_mode = getattr(frappe.conf, "developer_mode", 0)
            frappe.conf.developer_mode = 1
            try:
                page_doc.insert(ignore_permissions=True)
            finally:
                frappe.conf.developer_mode = orig_dev_mode
            frappe.db.commit()

            print(f"✅ Created page: {page_name}")

    # Register/Update NetraNext Workspace
    workspace_name = "NetraNext"
    if frappe.db.exists("Workspace", workspace_name):
        ws_doc = frappe.get_doc("Workspace", workspace_name)
        ws_doc.public = 1
        ws_doc.is_hidden = 0
        ws_doc.sequence_id = 1.0
        if hasattr(ws_doc, "type"):
            ws_doc.type = "Workspace"
        ws_doc.roles = []
        for role in roles_to_assign:
            ws_doc.append("roles", {"role": role})

        # Ensure content JSON contains Card blocks so canvas renders cards properly
        import json
        ws_content = [
            {"type": "header", "data": {"text": "<span class=\"h4\"><b>NetraNext</b></span>", "col": 12}},
            {"type": "card", "data": {"card_name": "Trips", "col": 4}},
            {"type": "card", "data": {"card_name": "Approvals", "col": 4}},
            {"type": "card", "data": {"card_name": "Setting", "col": 4}},
            {"type": "shortcut", "data": {"shortcut_name": "Dashboard", "col": 3}},
            {"type": "shortcut", "data": {"shortcut_name": "Live Tracking", "col": 3}},
            {"type": "shortcut", "data": {"shortcut_name": "Trip History", "col": 3}},
            {"type": "shortcut", "data": {"shortcut_name": "Approvals", "col": 3}},
        ]
        ws_doc.content = json.dumps(ws_content)

        ws_doc.save(ignore_permissions=True)
        frappe.db.commit()
        print(f"✅ Updated workspace permissions, sequence, and content layout for: {workspace_name}")
    else:
        print(f"⚠️ Workspace {workspace_name} not found in DB, standard import will create it on migrate.")

    # Register/Update NetraNext Workspace Sidebar (for Frappe v15/v16 sidebar navigation tree)
    sidebar_items = [
        {"label": "Dashboard", "type": "Link", "link_type": "Page", "link_to": "netranext-dashboard", "icon": "dashboard-list", "child_item": 0},
        {"label": "Live tracking Map", "type": "Link", "link_type": "Page", "link_to": "netranext-live-tracking", "icon": "map-pin", "child_item": 0},
        {"label": "Trips", "type": "Section Break", "icon": "scroll-text", "child_item": 0},
        {"label": "Scheduled Trips", "type": "Link", "link_type": "DocType", "link_to": "Scheduled Trip", "icon": "timer", "child_item": 1},
        {"label": "Trip History", "type": "Link", "link_type": "Page", "link_to": "netranext-trip-history", "icon": "history", "child_item": 1},
        {"label": "Trip Details", "type": "Link", "link_type": "Page", "link_to": "netranext-trip-details", "icon": "map", "child_item": 1},
        {"label": "Approvals", "type": "Section Break", "icon": "scroll-text", "child_item": 0},
        {"label": "Location Checkin Approvals", "type": "Link", "link_type": "DocType", "link_to": "NetraNext Location Checkin Approval", "icon": "map-pin-check", "child_item": 1},
        {"label": "Face Registration Request", "type": "Link", "link_type": "DocType", "link_to": "NetraNext Face Registration Request", "icon": "scan-face", "child_item": 1},
        {"label": "Setting", "type": "Section Break", "icon": "settings", "child_item": 0},
        {"label": "NetraNext Settings", "type": "Link", "link_type": "DocType", "link_to": "NetraNext Settings", "icon": "settings", "child_item": 1},
        {"label": "User Mappings", "type": "Link", "link_type": "DocType", "link_to": "NetraNext User Mapping", "icon": "users", "child_item": 1},
    ]

    if frappe.db.exists("DocType", "Workspace Sidebar"):
        try:
            if frappe.db.exists("Workspace Sidebar", workspace_name):
                sidebar_doc = frappe.get_doc("Workspace Sidebar", workspace_name)
                sidebar_doc.header_icon = "grid"
                sidebar_doc.items = []
                for item in sidebar_items:
                    sidebar_doc.append("items", item)
                sidebar_doc.save(ignore_permissions=True)
                frappe.db.commit()
                print(f"✅ Synced Workspace Sidebar items for: {workspace_name}")
            else:
                sidebar_doc = frappe.get_doc({
                    "doctype": "Workspace Sidebar",
                    "name": workspace_name,
                    "header_icon": "grid",
                    "items": sidebar_items
                })
                sidebar_doc.insert(ignore_permissions=True)
                frappe.db.commit()
                print(f"✅ Created Workspace Sidebar for: {workspace_name}")
        except Exception as e:
            print(f"⚠️ Could not sync Workspace Sidebar: {e}")

    # Ensure 'Installed Applications' single document includes netranext_client with has_setup_wizard=0
    try:
        ia_doc = frappe.get_doc("Installed Applications")
        found = False
        for row in ia_doc.installed_applications:
            if row.app_name == "netranext_client":
                row.has_setup_wizard = 0
                row.is_setup_complete = 1
                found = True
                break
        if not found:
            ia_doc.append("installed_applications", {
                "app_name": "netranext_client",
                "app_version": "1.0.0",
                "git_branch": "master",
                "has_setup_wizard": 0,
                "is_setup_complete": 1,
            })
        ia_doc.save(ignore_permissions=True)
        frappe.db.commit()
        print("✅ Registered netranext_client in Installed Applications single doc")
    except Exception as e:
        print(f"⚠️ Could not update Installed Applications: {e}")

    # Ensure NetraNext is not blocked in 'block_modules' for all active users
    users_updated = 0
    all_users = frappe.get_all("User", filters={"enabled": 1}, pluck="name")
    for user_email in all_users:
        if user_email in ("Guest",):
            continue
        try:
            user_doc = frappe.get_doc("User", user_email)
            modified = False
            if hasattr(user_doc, "block_modules") and user_doc.block_modules:
                orig_len = len(user_doc.block_modules)
                user_doc.block_modules = [m for m in user_doc.block_modules if m.module != "NetraNext"]
                if len(user_doc.block_modules) != orig_len:
                    modified = True
            if user_doc.user_type == "System User" and not user_doc.default_workspace:
                user_doc.default_workspace = "NetraNext"
                modified = True
            if modified:
                user_doc.save(ignore_permissions=True)
                users_updated += 1
            frappe.clear_cache(user=user_email)
        except Exception:
            pass
    frappe.clear_cache()
    print("🚀 NetraNext pages and workspace registration completed!")

