import frappe


def get_context(context):
    """
    Build context for the NetraNext Live Tracking page
    """
    context.title = "Live Tracking"
    context.api_endpoint = "/api/method/netranext_client.netranext.apis.v1.dashboard.get_dashboard_data"
    context.journey_api_endpoint = "/api/method/netranext_client.netranext.apis.v1.dashboard.get_dashboard_data"

    # Add CSRF token for API calls
    context.csrf_token = frappe.sessions.get_csrf_token()

    # Include CSS for the page
    context.css_include = "/assets/netranext_client/css/netranext_live_tracking.css"

    # Add Leaflet CSS/JS for map functionality
    context.leaflet_css = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    context.leaflet_js = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"

    return context
