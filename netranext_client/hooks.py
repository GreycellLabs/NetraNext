app_name = "netranext_client"
app_title = "NetraNext Client"
app_publisher = "meet"
app_description = "Client management app"
app_email = "meet.vaghasiya@egreycell.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "netranext_client",
# 		"logo": "/assets/netranext_client/logo.png",
# 		"title": "NetraNext Client",
# 		"route": "/netranext_client",
# 		"has_permission": "netranext_client.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/netranext_client/css/netranext_client.css"
# app_include_js = "/assets/netranext_client/js/netranext_client.js"

# include js, css files in header of web template
web_include_js = "/assets/netranext_client/config/api_config.js"
# web_include_css = "/assets/netranext_client/css/netranext_client.css"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "netranext_client/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# Page specific CSS
page_css = {
    "netranext-dashboard": "/assets/netranext_client/css/netranext_dashboard.css",
    "netranext-mapview": "/assets/netranext_client/css/netranext_mapview.css"
}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "netranext_client/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Custom Pages
# -------------

# Register custom pages for NetraNext
app_include_js = "/assets/netranext_client/js/pages.js"

# Page routes and icons
pages_dict = {
    "netranext-dashboard": {
        "title": "NetraNext Dashboard",
        "route": "/app/netranext-dashboard",
        "icon": "fa-dashboard",
        "roles": ["System Manager", "HR Manager", "HR User"]
    },
    "netranext-mapview": {
        "title": "Journey Map",
        "route": "/app/netranext-mapview",
        "icon": "fa-map",
        "roles": ["System Manager", "HR Manager", "HR User"]
    }
}

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "netranext_client.utils.jinja_methods",
# 	"filters": "netranext_client.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "netranext_client.install.before_install"
# after_install = "netranext_client.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "netranext_client.uninstall.before_uninstall"
# after_uninstall = "netranext_client.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "netranext_client.utils.before_app_install"
# after_app_install = "netranext_client.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "netranext_client.utils.before_app_uninstall"
# after_app_uninstall = "netranext_client.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "netranext_client.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"netranext_client.tasks.all"
# 	],
# 	"daily": [
# 		"netranext_client.tasks.daily"
# 	],
# 	"hourly": [
# 		"netranext_client.tasks.hourly"
# 	],
# 	"weekly": [
# 		"netranext_client.tasks.weekly"
# 	],
# 	"monthly": [
# 		"netranext_client.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "netranext_client.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "netranext_client.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "netranext_client.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["netranext_client.utils.before_request"]
# after_request = ["netranext_client.utils.after_request"]

# Job Events
# ----------
# before_job = ["netranext_client.utils.before_job"]
# after_job = ["netranext_client.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"netranext_client.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# NetraNext API Endpoints
# -------------------------------
# Whitelisted API methods for tenant bench sync
api_whitelisted_methods = [
    "netranext_client.netranext.apis.v1.sync.get_employee_data",
    "netranext_client.netranext.apis.v1.sync.get_employee_faces",
    "netranext_client.netranext.apis.v1.sync.store_attendance",
    "netranext_client.netranext.apis.v1.sync.store_face",
    "netranext_client.netranext.apis.v1.sync.store_journey",
    "netranext_client.netranext.apis.v1.sync.update_employee_device_id",
    "netranext_client.netranext.apis.v1.sync.health_check",
    "netranext_client.netranext.apis.v1.dashboard.get_dashboard_data",
]

# Custom Fields
# -------------------------------
custom_fields = {
    "Employee Checkin": [
        {
            "fieldname": "log_type_col",
            "fieldtype": "Column Break",
            "insert_after": "log_type"
        },
        {
            "fieldname": "attendance_proof_section",
            "fieldtype": "Section Break",
            "label": "Attendance Proof",
            "insert_after": "skip_auto_attendance"
        },
        {
            "fieldname": "photo_proof",
            "fieldtype": "Attach Image",
            "label": "Photo Proof",
            "insert_after": "attendance_proof_section",
            "hidden": 0,
            "reqd": 0,
            "read_only": 1,
            "description": "Actual photo captured during attendance"
        },
        {
            "fieldname": "attendance_proof_col",
            "fieldtype": "Column Break",
            "insert_after": "photo_proof"
        },
        {
            "fieldname": "location_address",
            "fieldtype": "Text",
            "label": "Location Address",
            "insert_after": "attendance_proof_col",
            "hidden": 0,
            "reqd": 0,
            "read_only": 1
        }
    ]
}

# CORS Configuration for Central Server Access
# --------------------------------------------
allow_cors_requests = [
    "netranext.apis.v1.*"
]

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

