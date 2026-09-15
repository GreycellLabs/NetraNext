import frappe


def boot_session(bootinfo):
    """
    Extend bootinfo for NetraNext workspace.
    Ensures that every logged-in system user has NetraNext set as their default workspace
    if they do not already have a specific default_workspace configured.
    """
    if bootinfo and hasattr(bootinfo, "user") and bootinfo.user:
        if not bootinfo.user.get("default_workspace"):
            bootinfo.user["default_workspace"] = {
                "name": "NetraNext",
                "public": 1,
                "title": "NetraNext",
            }
