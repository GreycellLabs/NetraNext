"""Create missing NetraNext navigation records; never reset site customizations."""
import json
from pathlib import Path

import frappe

WORKSPACE = "NetraNext"
ICON_LABEL = "Netranext"
APP = "netranext_client"


def _insert(data):
    # Supported document import context prevents developer-mode export from
    # writing generated files into the installed app during setup/migration.
    previous = frappe.flags.get("in_import")
    frappe.flags.in_import = True
    try:
        doc = frappe.get_doc(data)
        doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
        return doc
    finally:
        frappe.flags.in_import = previous


def ensure_workspace():
    if frappe.db.exists("Workspace", WORKSPACE):
        return frappe.get_doc("Workspace", WORKSPACE)
    path = Path(frappe.get_app_path(APP, "netranext", "workspace", "netranext", "netranext.json"))
    data = json.loads(path.read_text())
    for key in ("creation", "modified", "modified_by", "owner"):
        data.pop(key, None)
    data["owner"] = "Administrator"
    # The app can be installed before optional HR roles are available.
    data["roles"] = [r for r in data.get("roles", []) if frappe.db.exists("Role", r["role"])]
    _insert(data)
    return frappe.get_doc("Workspace", WORKSPACE)


def ensure_sidebar(workspace):
    if frappe.db.exists("Workspace Sidebar", WORKSPACE):
        return
    items = [{"label": "Home", "type": "Link", "link_type": "Workspace", "link_to": WORKSPACE,
              "icon": "home", "child": 0}]
    in_section = False
    for link in workspace.get("links") or []:
        if link.get("hidden"):
            continue
        if link.get("type") == "Card Break":
            items.append({"label": link.label, "type": "Section Break", "child": 0})
            in_section = True
        elif link.get("link_to") and link.get("link_type") in ("DocType", "Page", "Report", "Workspace"):
            if frappe.db.exists(link.link_type, link.link_to):
                items.append({"label": link.label, "type": "Link", "link_type": link.link_type,
                              "link_to": link.link_to, "icon": link.get("icon"), "child": int(in_section)})
    _insert({"doctype": "Workspace Sidebar", "title": WORKSPACE, "header_icon": workspace.get("icon") or "grid",
             "module": workspace.get("module"), "items": items, "owner": "Administrator"})


def ensure_desktop_setup():
    workspace = ensure_workspace()
    # Respect intentional private/hidden workspaces; do not publish them via
    # a new shared launcher icon or alter their permission configuration.
    if not workspace.get("public") or workspace.get("for_user") or workspace.get("is_hidden"):
        return {"status": "preserved_private_or_hidden_workspace"}
    if not frappe.db.exists("DocType", "Workspace Sidebar"):
        frappe.logger(APP).info("Skipping v16 desktop setup: Workspace Sidebar is unavailable on this site.")
        return {"status": "unsupported_desktop_schema"}  # Frappe v15
    ensure_sidebar(workspace)
    if not frappe.db.exists("DocType", "Desktop Icon"):
        # Evolving v16 builds may retire the deprecated desktop grid while
        # keeping sidebars; the sidebar remains useful navigation.
        frappe.logger(APP).info("Desktop Icon schema is unavailable; created the sidebar only.")
        return {"status": "sidebar_only", "sidebar": WORKSPACE}
    meta = frappe.get_meta("Desktop Icon")
    if not all(meta.has_field(f) for f in ("label", "icon_type", "link_type", "link_to")):
        frappe.logger(APP).info("Skipping v16 desktop setup: Desktop Icon uses a different schema.")
        return {"status": "unsupported_desktop_schema"}
    # Reuse manual or standard icons even if the administrator changed the label,
    # ordering, visibility, colour or roles. Do not seed a second target icon.
    existing = frappe.db.get_value("Desktop Icon", {"icon_type": "Link", "link_type": "Workspace Sidebar",
                                                    "link_to": WORKSPACE}, "name")
    if existing:
        return {"status": "preserved", "icon": existing}
    if frappe.db.exists("Desktop Icon", ICON_LABEL):
        frappe.logger(APP).warning("Desktop Icon Netranext already exists with another target; preserving it.")
        return {"status": "name_conflict", "icon": ICON_LABEL}
    data = {"doctype": "Desktop Icon", "label": ICON_LABEL, "icon_type": "Link",
            "link_type": "Workspace Sidebar", "link_to": WORKSPACE, "idx": 0,
            "hidden": 0, "standard": 1, "app": APP, "owner": "Administrator",
            "roles": [{"role": role.role} for role in workspace.get("roles") or []]}
    if meta.has_field("bg_color"):
        data["bg_color"] = "gray"
    if meta.has_field("sidebar"):
        data["sidebar"] = WORKSPACE
    icon = _insert(data)
    # Older v16 controllers clear only the installing user's icon cache.
    frappe.cache.delete_key("desktop_icons")
    frappe.cache.delete_key("bootinfo")
    return {"status": "created", "icon": icon.name}
