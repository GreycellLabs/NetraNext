import json
import base64
import gzip
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


def _decode_trip_status_log(raw):
    """
    Decode the trip health log stored on the Journey doc.

    The mobile app stores it as JSON-lines (one JSON object per line),
    gzip-compressed and base64 encoded. A plain JSON-lines fallback is
    also supported.

    Returns a list of entry dicts sorted by timestamp.
    """
    if not raw:
        return []

    text = None
    try:
        compressed = base64.b64decode(raw)
        text = gzip.decompress(compressed).decode("utf-8")
    except Exception:
        text = None

    if text is None:
        # Fallback: plain (uncompressed) JSON-lines
        try:
            if "\n" in raw or raw.strip().startswith("{"):
                text = raw
        except Exception:
            return []

    if not text:
        return []

    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue

    entries.sort(key=lambda x: str(x.get("t", "")))
    return entries


def _utc_to_system_tz_str(value):
    """
    Convert a UTC timestamp to the system timezone and format it as
    'YYYY-MM-DD HH:mm:ss' for display.

    Used for Frappe Datetime docfields (always stored in UTC) - both
    datetime objects and naive 'YYYY-MM-DD HH:mm:ss' strings.
    Returns None when value is empty; falls back to the raw string when it
    cannot be parsed.
    """
    if not value:
        return None

    try:
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return str(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    local_dt = frappe.utils.convert_utc_to_system_timezone(dt).replace(tzinfo=None)
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def _iso_display_tz_str(value):
    """
    Normalize an ISO timestamp from the mobile app for display.

    - Strings with a UTC marker ('Z' or offset): UTC -> system timezone.
    - Naive strings without a marker: older app versions recorded the
      phone's local wall time in the health log - show them as-is
      (only normalized to a consistent format for sorting).
    """
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return str(value)

    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    local_dt = frappe.utils.convert_utc_to_system_timezone(dt).replace(tzinfo=None)
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


# The Event Timeline intentionally shows ONLY 4 event types:
# 1. Trip Started  2. Trip Ended  3. User Offline  4. User Online
# (Trip Start/End are built from the Journey doc fields; only network
# lost/back events come from the health log). Every other health event
# (battery, app background, background service, sync checks) remains
# available in the Trip Health Log card below.
TIMELINE_HEALTH_EVENTS = {
    "NETWORK_LOST": (
        "User Offline",
        "Network connection lost - GPS points could not be sent to the server.",
        "fa-wifi-slash",
    ),
    "NETWORK_BACK": (
        "User Online",
        "Network connection restored - pending GPS points can now sync.",
        "fa-wifi",
    ),
}


def _health_events_for_timeline(entries):
    """
    Convert health log connection events into the timeline_events format.
    Only network lost/back events are surfaced (User Offline / User Online);
    the full health log remains server-side only.
    """
    events = []
    for e in entries:
        etype = e.get("e")
        meta = TIMELINE_HEALTH_EVENTS.get(etype)
        if not meta:
            continue
        title, details, icon = meta
        reason = e.get("reason")
        events.append({
            "timestamp": _iso_display_tz_str(e.get("t")) or "",
            "type": etype,
            "title": title,
            "details": f"{details} {(' - ' + str(reason)) if reason else ''}".strip(),
            "icon": icon,
        })
    return events


def _app_journey_metadata(meta):
    """
    Return the mobile app journey's own metadata dict.

    The central server stores the app's full journey JSON wrapped as
    ``metadata.flutter_data`` (see netranext.apis.v1.journey.create_journeys),
    so the phone's end-reason + telemetry actually live at
    ``flutter_data.metadata.{end_reason, telemetry}`` - NOT at the top level
    of the doc metadata. Older shapes kept them at the top level; support both.
    """
    if not isinstance(meta, dict):
        return {}
    inner = (meta.get("flutter_data") or {}).get("metadata") or {}
    if isinstance(inner, dict) and inner:
        return inner
    return meta


def _build_device_telemetry(meta, health_entries, raw_gps):
    """
    Build the Device & Telemetry card payload.

    Device details arrive from three sources (first found wins per field):
    - the app telemetry embedded in the journey payload
      (metadata.flutter_data.metadata.telemetry.{device,battery,gps_stats})
    - the trip health log (battery level, network type, GPS points recorded
      every 10s on the phone) stored in trip_status_log
    - legacy shapes: top-level metadata.telemetry / flutter_data.deviceInfo
    """
    app_meta = _app_journey_metadata(meta)

    legacy = meta.get("telemetry") or {}
    app_telemetry = app_meta.get("telemetry") or {}

    device = dict(legacy.get("device") or {})
    battery = dict(legacy.get("battery") or {})
    gps_stats = dict(legacy.get("gps_stats") or {})

    # Current storage shape: telemetry nested inside flutter_data.metadata
    for section, target in (
        ("device", device),
        ("battery", battery),
        ("gps_stats", gps_stats),
    ):
        for key, value in (app_telemetry.get(section) or {}).items():
            if value is not None:
                target.setdefault(key, value)

    # Older payload shape: flat deviceInfo next to flutter_data
    device_info = (meta.get("flutter_data") or {}).get("deviceInfo") or {}
    if device_info.get("model"):
        device.setdefault("model", device_info["model"])
    if device_info.get("os_version"):
        device.setdefault("os_version", device_info["os_version"])

    status_entries = [e for e in health_entries if e.get("e") == "STATUS"]
    if status_entries:
        first = status_entries[0]
        last = status_entries[-1]

        net_type = (first.get("net") or {}).get("type")
        if net_type:
            device.setdefault("network_type_at_start", net_type)

        start_lvl = (first.get("bat") or {}).get("lvl")
        end_lvl = (last.get("bat") or {}).get("lvl")
        if isinstance(start_lvl, (int, float)):
            battery.setdefault("start_level", start_lvl)
        if isinstance(end_lvl, (int, float)):
            battery.setdefault("end_level", end_lvl)
        if isinstance(start_lvl, (int, float)) and isinstance(end_lvl, (int, float)):
            battery["total_consumed_pct"] = max(int(start_lvl) - int(end_lvl), 0)

        # Android: True = battery optimization still active (tracking risk)
        bat_opt = (last.get("bat") or {}).get("opt")
        if isinstance(bat_opt, bool):
            battery["battery_optimization_active"] = bat_opt

        collected = (last.get("pts") or {}).get("col")
        if isinstance(collected, (int, float)):
            gps_stats.setdefault("total_points_captured", int(collected))

    if "total_points_captured" not in gps_stats and raw_gps:
        gps_stats["total_points_captured"] = len(raw_gps)

    return {"device": device, "battery": battery, "gps_stats": gps_stats}


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
        # Convert from UTC (storage) to system timezone for display
        start_time_str = "-"
        journey_date_str = "-"
        if j.start_time:
            local_str = _utc_to_system_tz_str(j.start_time)
            if local_str:
                try:
                    dt = datetime.strptime(local_str, "%Y-%m-%d %H:%M:%S")
                    start_time_str = dt.strftime("%d-%m-%Y %H:%M:%S")
                    journey_date_str = dt.strftime("%d-%m-%Y")
                except Exception:
                    start_time_str = local_str
                    journey_date_str = local_str.split(" ")[0] if " " in local_str else local_str

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
    # The timeline shows ONLY: Trip Started, User Offline, User Online, Trip Ended
    timeline_events = []

    # Convert from UTC (Frappe storage / mobile app) to system timezone
    start_time_str = _utc_to_system_tz_str(doc.start_time) or "N/A"
    timeline_events.append({
        "timestamp": start_time_str,
        "type": "TRIP_START",
        "title": "Trip Started",
        "details": f"Started at {doc.start_location or 'Initial Location'}",
        "icon": "fa-play-circle"
    })

    # Trip Health Log (10s device status log from the phone)
    # Decoded for timeline connection events and telemetry only; the full log
    # and its summary are server-side data and are NOT sent to the client page.
    health_entries = _decode_trip_status_log(getattr(doc, "trip_status_log", None))

    # User Offline / User Online events from the health log (current source)
    connection_events = _health_events_for_timeline(health_entries)

    # Fallback for trips recorded before the health log existed: legacy
    # network events embedded in the metadata telemetry (top level or inside
    # the wrapped flutter_data payload)
    if not connection_events:
        legacy_network_events = (
            (meta.get("telemetry") or {}).get("network_events")
            or (_app_journey_metadata(meta).get("telemetry") or {}).get("network_events")
            or []
        )
        for net_ev in legacy_network_events:
            event_type = net_ev.get("event", "")
            ts = _iso_display_tz_str(net_ev.get("timestamp")) or start_time_str
            if event_type == "OFFLINE_DISCONNECT":
                connection_events.append({
                    "timestamp": ts,
                    "type": "NETWORK_OFFLINE",
                    "title": "User Offline",
                    "details": "Network connection lost - GPS points could not be sent to the server.",
                    "icon": "fa-wifi-slash"
                })
            elif event_type == "ONLINE_RECONNECTED":
                connection_events.append({
                    "timestamp": ts,
                    "type": "NETWORK_ONLINE",
                    "title": "User Online",
                    "details": f"Network connection restored via {net_ev.get('type', 'Mobile/Wi-Fi')}.",
                    "icon": "fa-wifi"
                })

    timeline_events.extend(connection_events)

    # Device & Telemetry card payload (merged from health log + metadata)
    telemetry = _build_device_telemetry(meta, health_entries, raw_gps)

    end_time_str = _utc_to_system_tz_str(doc.end_time) or "In Progress"

    end_reason_code = (
        meta.get("end_reason")
        or _app_journey_metadata(meta).get("end_reason")
        or ("User manually tapped End Journey" if doc.status == "Completed" else "Trip still active")
    )
    
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
        "journey_date": start_time_str.split(" ")[0] if doc.start_time else "",
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
