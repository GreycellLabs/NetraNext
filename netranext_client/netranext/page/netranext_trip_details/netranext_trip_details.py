import json
import frappe
from frappe import _
from datetime import datetime, timezone


def get_context(context):
    """
    Build context for the NetraNext Trip Details page
    """
    context.title = "Trip Details"
    context.csrf_token = frappe.sessions.get_csrf_token()
    return context


@frappe.whitelist()
def get_all_trips_summary(employee=None, status=None, date=None, search=None, limit=100):
    """
    Fetch a list of all NetraNext Journey records for the list view with filtering.
    Format columns to match standard Frappe DocType List View.
    """
    if not frappe.db.exists("DocType", "NetraNext Journey"):
        return []

    filters = {}
    or_filters = []
    if employee and str(employee).strip():
        filters["employee"] = ["like", f"%{str(employee).strip()}%"]
    if status and str(status).strip():
        filters["status"] = str(status).strip()
    if date and str(date).strip():
        d_str = str(date).strip()
        filters["start_time"] = ["between", [f"{d_str} 00:00:00", f"{d_str} 23:59:59"]]

    if search and str(search).strip():
        s = f"%{str(search).strip()}%"
        or_filters = [
            ["name", "like", s],
            ["employee", "like", s],
            ["journey_name", "like", s]
        ]

    limit = int(limit) if limit else 100

    journeys = frappe.get_all(
        "NetraNext Journey",
        filters=filters if filters else None,
        or_filters=or_filters if or_filters else None,
        fields=[
            "name",
            "journey_name",
            "employee",
            "start_time",
            "end_time",
            "status",
            "distance_km",
            "duration_seconds",
            "creation",
            "metadata"
        ],
        order_by="creation desc",
        limit=limit
    )

    now = datetime.now()

    for j in journeys:
        # Format Start Time (DD-MM-YYYY HH:mm:ss) & Journey Date
        start_time_str = "-"
        journey_date_str = "-"
        if j.start_time:
            try:
                dt = j.start_time if isinstance(j.start_time, datetime) else datetime.fromisoformat(str(j.start_time).replace("Z", ""))
                start_time_str = dt.strftime("%d-%m-%Y %H:%M:%S")
                journey_date_str = dt.strftime("%d-%m-%Y")
            except Exception:
                start_time_str = str(j.start_time)
                journey_date_str = str(j.start_time).split(" ")[0] if " " in str(j.start_time) else str(j.start_time)

        j["start_time_formatted"] = start_time_str
        j["journey_date"] = journey_date_str

        # Format Duration
        dur_sec = j.duration_seconds or 0
        if dur_sec < 60:
            j["duration_formatted"] = "0 min"
        elif dur_sec < 3600:
            j["duration_formatted"] = f"{int(dur_sec // 60)} min"
        else:
            hours = int(dur_sec // 3600)
            mins = int((dur_sec % 3600) // 60)
            j["duration_formatted"] = f"{hours}h {mins}m" if mins > 0 else f"{hours}h"

        # Format Time Ago (e.g. 4 h, 1 d, 1 w)
        time_ago = "-"
        if j.creation:
            try:
                c_dt = j.creation if isinstance(j.creation, datetime) else datetime.fromisoformat(str(j.creation).replace("Z", ""))
                c_dt_naive = c_dt.replace(tzinfo=None) if hasattr(c_dt, 'tzinfo') and c_dt.tzinfo else c_dt
                diff = now - c_dt_naive
                days = diff.days
                secs = diff.seconds
                if days == 0:
                    hours = secs // 3600
                    time_ago = f"{hours} h" if hours > 0 else "Just now"
                elif days < 7:
                    time_ago = f"{days} d"
                elif days < 30:
                    time_ago = f"{days // 7} w"
                else:
                    time_ago = f"{days // 30} m"
            except Exception:
                pass
        j["time_ago"] = time_ago

        # Distance formatting
        j["distance_formatted"] = f"{(j.distance_km or 0.0):.2f} km" if (j.distance_km or 0.0) > 0 else "0 km"

        # Parse End Reason from Metadata
        end_reason = "Completed" if j.status == "Completed" else "In Progress"
        if j.metadata:
            try:
                meta = json.loads(j.metadata) if isinstance(j.metadata, str) else j.metadata
                reason_code = meta.get("end_reason")
                reason_map = {
                    "MANUAL_USER_BUTTON_TAP": "User manually tapped End Journey",
                    "WATCHDOG_INACTIVITY_TIMEOUT": "Auto-stopped (Inactivity timeout)",
                    "OS_KILLED_ISOLATE_RECOVERY": "Auto-stopped (OS memory recovery)",
                    "GPS_PERMISSION_REVOKED": "Location permission revoked",
                    "CRITICAL_LOW_BATTERY": "Low battery auto-stop"
                }
                if reason_code in reason_map:
                    end_reason = reason_map[reason_code]
                elif reason_code:
                    end_reason = reason_code
            except Exception:
                pass
        j["end_reason"] = end_reason

    return journeys


@frappe.whitelist()
def get_trip_telemetry_details(trip_id=None):
    """
    Fetch comprehensive journey details, coordinates, device telemetry logs,
    network connection events, and end trip reasons for a given trip ID.
    """
    if not trip_id:
        frappe.throw(_("Trip ID is required"))

    # Try finding by DocName first, then by flutter_journey_id
    journey_name = trip_id
    if not frappe.db.exists("NetraNext Journey", journey_name):
        matched = frappe.db.get_value("NetraNext Journey", {"flutter_journey_id": trip_id}, "name")
        if matched:
            journey_name = matched
        else:
            frappe.throw(_("NetraNext Journey {0} not found").format(trip_id))

    doc = frappe.get_doc("NetraNext Journey", journey_name)

    # Parse raw GPS data / coordinates
    raw_gps = []
    if hasattr(doc, "raw_gps_data") and doc.raw_gps_data:
        try:
            raw_gps = json.loads(doc.raw_gps_data) if isinstance(doc.raw_gps_data, str) else doc.raw_gps_data
        except Exception:
            raw_gps = []
    elif hasattr(doc, "raw_coordinates") and doc.raw_coordinates:
        try:
            raw_gps = json.loads(doc.raw_coordinates) if isinstance(doc.raw_coordinates, str) else doc.raw_coordinates
        except Exception:
            raw_gps = []

    # Parse Metadata JSON (Device Battery, Signal Events, End Reason)
    meta = {}
    if hasattr(doc, "metadata") and doc.metadata:
        try:
            meta = json.loads(doc.metadata) if isinstance(doc.metadata, str) else doc.metadata
        except Exception:
            meta = {}

    # Extract employee name
    employee_name = doc.employee
    if doc.employee and frappe.db.exists("Employee", doc.employee):
        emp_doc = frappe.get_value("Employee", doc.employee, ["employee_name", "first_name", "last_name"], as_dict=True)
        if emp_doc:
            employee_name = emp_doc.get("employee_name") or f"{emp_doc.get('first_name', '')} {emp_doc.get('last_name', '')}".strip()

    # Build Chronological Timeline Events
    timeline_events = []

    start_time_str = str(doc.start_time) if doc.start_time else "N/A"
    timeline_events.append({
        "timestamp": start_time_str,
        "type": "TRIP_START",
        "title": "Trip Started",
        "details": f"Started at {doc.start_location or 'Initial Location'}",
        "icon": "fa-play-circle"
    })

    # Telemetry events from Metadata JSON
    telemetry = meta.get("telemetry", {})
    network_events = telemetry.get("network_events", [])
    for net_ev in network_events:
        event_type = net_ev.get("event", "")
        ts = net_ev.get("timestamp", start_time_str)
        if event_type == "OFFLINE_DISCONNECT":
            timeline_events.append({
                "timestamp": ts,
                "type": "NETWORK_OFFLINE",
                "title": "Device Went Offline",
                "details": "Mobile internet connection dropped. GPS satellite tracking continued locally.",
                "icon": "fa-wifi-slash"
            })
        elif event_type == "ONLINE_RECONNECTED":
            timeline_events.append({
                "timestamp": ts,
                "type": "NETWORK_ONLINE",
                "title": "Network Reconnected",
                "details": f"Connection restored via {net_ev.get('type', 'Mobile/Wi-Fi')}.",
                "icon": "fa-wifi"
            })

    end_time_str = str(doc.end_time) if doc.end_time else "In Progress"
    end_reason_code = meta.get("end_reason") or ("User manually tapped End Journey" if doc.status == "Completed" else "Trip still active")
    
    reason_map = {
        "MANUAL_USER_BUTTON_TAP": "User manually tapped 'End Journey' in mobile app",
        "WATCHDOG_INACTIVITY_TIMEOUT": "Auto-stopped by background watchdog after 5 min inactivity",
        "OS_KILLED_ISOLATE_RECOVERY": "App process was recovered after OS memory optimization",
        "GPS_PERMISSION_REVOKED": "GPS location permissions were turned off mid-trip",
        "CRITICAL_LOW_BATTERY": "Auto-stopped due to critical low battery threshold"
    }
    human_end_reason = reason_map.get(end_reason_code, end_reason_code)

    if doc.status == "Completed":
        timeline_events.append({
            "timestamp": end_time_str,
            "type": "TRIP_END",
            "title": "Trip Ended",
            "details": f"End Reason: {human_end_reason}",
            "icon": "fa-flag-checkered"
        })

    try:
        timeline_events.sort(key=lambda x: str(x["timestamp"]))
    except Exception:
        pass

    return {
        "trip_id": doc.name,
        "flutter_journey_id": getattr(doc, "flutter_journey_id", None),
        "employee_id": doc.employee,
        "employee_name": employee_name,
        "status": doc.status,
        "journey_date": str(doc.start_time).split(" ")[0] if doc.start_time else "",
        "start_time": start_time_str,
        "end_time": end_time_str,
        "start_location": doc.start_location or "N/A",
        "end_location": doc.end_location or "N/A",
        "distance_km": doc.distance_km or 0.0,
        "duration_seconds": getattr(doc, "duration_seconds", None) or 0,
        "end_reason": human_end_reason,
        "raw_gps_data": raw_gps,
        "telemetry": telemetry,
        "timeline_events": timeline_events
    }
