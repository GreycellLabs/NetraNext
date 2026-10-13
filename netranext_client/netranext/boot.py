import frappe


def has_app_permission():
    """
    Callback for add_to_apps_screen in hooks.py.
    Ensures NetraNext app card is visible on /app/apps launcher for all logged-in system users.
    """
    return True


def on_session_creation(login_manager):
    """
	Drop the logging-in user's cached permission sets (user_allowed_modules,
	user_perm_can_read, has_role:Page/Report, ...) so every fresh login
	evaluates roles/modules from current DB state.

	Reason: User.on_update clears these caches only when the User doc is
	saved directly. Bulk role edits (list-view "Add Role" / db.set_value)
	skip that invalidation, and Frappe then serves the stale module list
	for up to 6 hours — which silently hides the NetraNext workspace and
	app tile for that user.
	"""
    user = getattr(login_manager, "user", None)
    if not user or user in ("Guest", "Administrator"):
        return

    try:
        frappe.cache.delete_keys("user:" + user)
    except Exception:
        frappe.log_error(
            title="NetraNext Client: failed to purge user permission cache on login",
            message=frappe.get_traceback(),
        )


def boot_session(bootinfo):
    """
    Extend bootinfo if required.
    """
    pass

