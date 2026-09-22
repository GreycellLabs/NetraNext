import frappe


def has_app_permission():
    """
    Callback for add_to_apps_screen in hooks.py.
    Ensures NetraNext app card is visible on /app/apps launcher for all logged-in system users.
    """
    return True


def boot_session(bootinfo):
    """
    Extend bootinfo if required.
    """
    pass

