import frappe

def execute():
    """
    Patch to register NetraNext custom pages in the database
    This ensures the pages show up in the Page list and are accessible
    """
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
            "name": "netranext-mapview",
            "page_name": "netranext-mapview",
            "module": "NetraNext",
            "standard": "Yes",
            "system_page": 1,
            "title": "Journey Map",
            "icon": "fa-map"
        }
    ]

    # Define roles to assign
    roles_to_assign = ["System Manager", "HR Manager", "HR User"]

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

    print("🚀 NetraNext pages registration completed!")
