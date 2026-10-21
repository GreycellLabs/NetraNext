import json
import base64
import gzip
import frappe
from frappe import _
from datetime import datetime, timedelta, timezone


def get_context(context):
    """
    Build context for the NetraNext Trip Details page
    """
    context.title = "Trip Details"
    context.csrf_token = frappe.sessions.get_csrf_token()
    return context


def _system_zone():
    """
    Tenant system timezone as a tzinfo.

    Journey actual start/end are stored as naive datetimes written by the
    Service bench in ITS system timezone (see netranext.apis.v1.journey.
    parse_iso_datetime); in this deployment both benches share one zone, so
    the tenant system zone is the storage zone for those columns. Frappe's
    own Datetime fields (creation/modified) remain UTC and are handled
    separately.
    """
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(frappe.utils.get_system_timezone())
    except Exception:
        return timezone.utc


def _parse_dt(value):
    """Parse a datetime or ISO string; returns None when unparseable."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except Exception:
        return None


def _journey_dt_to_utc(value):
    """
    Interpret a stored Journey actual start/end timestamp.

    Naive values are wall time in the storage zone (system zone, see
    _system_zone); values carrying Z/offset keep their zone. Returns
    (aware UTC datetime or None, system-zone display string or None).
    """
    dt = _parse_dt(value)
    if dt is None:
        return None, (str(value) if value else None)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_system_zone())
    return dt.astimezone(timezone.utc), dt.strftime("%Y-%m-%d %H:%M:%S")


def _viewer_day_to_storage_bounds(date_str, viewer_timezone):
    """
    Convert a viewer-local calendar day ('YYYY-MM-DD' in viewer_timezone)
    to naive [start, end) bounds in the storage timezone (system zone).

    Returns None when viewer_timezone is absent/unknown (legacy callers keep
    the naive system-day filter).
    """
    if not viewer_timezone:
        return None
    try:
        from zoneinfo import ZoneInfo
        viewer_zone = ZoneInfo(str(viewer_timezone))
        day = datetime.strptime(str(date_str).strip(), "%Y-%m-%d")
        start = day.replace(tzinfo=viewer_zone).astimezone(_system_zone()).replace(tzinfo=None)
        end = (day + timedelta(days=1)).replace(tzinfo=viewer_zone).astimezone(_system_zone()).replace(tzinfo=None)
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _event_instant_and_display(raw):
    """
    Instant + display for telemetry timestamps (health log, legacy network
    events, GPS points).

    Mobile timestamps are UTC ISO ('Z'/offset) and are converted to the
    system zone; naive values come from older app versions that logged the
    phone's local wall time and are shown as recorded (same deployment
    zone), using that zone for ordering.
    """
    dt = _parse_dt(raw)
    if dt is None:
        return None, (str(raw) if raw else None)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_system_zone())
    return dt.timestamp(), dt.astimezone(_system_zone()).strftime("%Y-%m-%d %H:%M:%S")


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

# Both capture paths (TripHealthLogger on the phone, legacy telemetry
# network_events) can record the same physical connectivity transition with
# slightly different timestamps. Only same-direction transitions within this
# window are considered duplicates; a real offline->online->offline cycle
# always takes longer.
CONNECTION_DEDUPE_TOLERANCE_SECONDS = 5


def _health_transition_candidates(entries):
    """Connection transitions from the trip health log (current source)."""
    candidates = []
    for e in entries:
        meta = TIMELINE_HEALTH_EVENTS.get(e.get("e"))
        if not meta:
            continue
        title, details, icon = meta
        reason = e.get("reason")
        instant, display = _event_instant_and_display(e.get("t"))
        candidates.append({
            "direction": "OFFLINE" if e.get("e") == "NETWORK_LOST" else "ONLINE",
            "instant": instant,
            "source_rank": 0,  # health log preferred over legacy telemetry
            "seq": len(candidates),
            "event": {
                "timestamp": display or "",
                "type": e.get("e"),
                "title": title,
                "details": f"{details} {(' - ' + str(reason)) if reason else ''}".strip(),
                "icon": icon,
                "source": "health",
            },
        })
    return candidates


def _legacy_transition_candidates(meta):
    """Connection transitions from legacy telemetry network_events (trips
    recorded before the health log existed)."""
    network_events = (
        (meta.get("telemetry") or {}).get("network_events")
        or (_app_journey_metadata(meta).get("telemetry") or {}).get("network_events")
        or []
    )
    candidates = []
    for net_ev in network_events:
        event_type = net_ev.get("event", "")
        if event_type not in ("OFFLINE_DISCONNECT", "ONLINE_RECONNECTED"):
            continue
        instant, display = _event_instant_and_display(net_ev.get("timestamp"))
        if event_type == "OFFLINE_DISCONNECT":
            candidates.append({
                "direction": "OFFLINE",
                "instant": instant,
                "source_rank": 1,
                "seq": len(candidates),
                "event": {
                    "timestamp": display or "",
                    "type": "NETWORK_OFFLINE",
                    "title": "User Offline",
                    "details": "Network connection lost - GPS points could not be sent to the server.",
                    "icon": "fa-wifi-slash",
                    "source": "legacy",
                },
            })
        else:
            candidates.append({
                "direction": "ONLINE",
                "instant": instant,
                "source_rank": 1,
                "seq": len(candidates),
                "event": {
                    "timestamp": display or "",
                    "type": "NETWORK_ONLINE",
                    "title": "User Online",
                    "details": f"Network connection restored via {net_ev.get('type', 'Mobile/Wi-Fi')}.",
                    "icon": "fa-wifi",
                    "source": "legacy",
                },
            })
    return candidates


def _merged_connection_events(health_entries, meta):
    """
    Timeline Online/Offline events from BOTH sources, always merged.

    The health log and the legacy telemetry network_events describe the same
    connectivity transitions; suppressing one source when the other exists
    loses events that only it captured (e.g. a health log holding only the
    Offline transition used to hide the legacy Online reconnect).
    Same-direction transitions within CONNECTION_DEDUPE_TOLERANCE_SECONDS
    are treated as one transition (health capture kept).
    """
    candidates = _health_transition_candidates(health_entries) + _legacy_transition_candidates(meta)
    candidates.sort(key=lambda c: (
        1 if c["instant"] is None else 0,
        c["instant"] if c["instant"] is not None else 0.0,
        c["source_rank"],
        c["seq"],
    ))

    kept = []
    for cand in candidates:
        duplicate = False
        if cand["instant"] is not None:
            for other in kept:
                if (
                    other["direction"] == cand["direction"]
                    and other["instant"] is not None
                    and abs(other["instant"] - cand["instant"]) <= CONNECTION_DEDUPE_TOLERANCE_SECONDS
                ):
                    duplicate = True
                    break
        if not duplicate:
            kept.append(cand)

    events = []
    for cand in kept:
        event = cand["event"]
        event["timestamp_utc"] = (
            datetime.fromtimestamp(cand["instant"], tz=timezone.utc).isoformat().replace("+00:00", "Z")
            if cand["instant"] is not None
            else None
        )
        events.append(event)
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
def get_all_trips_summary(employee=None, status=None, date=None, search=None, limit=100, viewer_timezone=None):
    """
    Fetch a list of all NetraNext Journey records for the list view with filtering.
    Format columns to match standard Frappe DocType List View.

    viewer_timezone (optional IANA zone from the browser): the `date` filter
    is then resolved as that viewer's local day converted to the storage
    timezone (exclusive end) instead of naive system-day bounds. Callers
    omitting it keep the legacy behaviour.
    """
    if not frappe.db.exists("DocType", "NetraNext Journey"):
        return []

    filters = []
    or_filters = []
    if employee and str(employee).strip():
        filters.append(["employee", "like", f"%{str(employee).strip()}%"])
    if status and str(status).strip():
        filters.append(["status", "=", str(status).strip()])
    if date and str(date).strip():
        d_str = str(date).strip()
        tz_bounds = _viewer_day_to_storage_bounds(d_str, viewer_timezone)
        if tz_bounds:
            filters.append(["start_time", ">=", tz_bounds[0]])
            filters.append(["start_time", "<", tz_bounds[1]])
        else:
            filters.append(["start_time", "between", [f"{d_str} 00:00:00", f"{d_str} 23:59:59"]])

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

    for j in journeys:
        # Format Start Time (DD-MM-YYYY HH:mm:ss) & Journey Date in the
        # storage timezone (system zone wall time - the stored value itself;
        # it is NOT UTC for these Service-written columns).
        start_utc, start_display = _journey_dt_to_utc(j.start_time)
        j["start_time_utc"] = start_utc.isoformat().replace("+00:00", "Z") if start_utc else None
        end_utc, end_display = _journey_dt_to_utc(j.end_time)
        j["end_time_utc"] = end_utc.isoformat().replace("+00:00", "Z") if end_utc else None

        start_time_str = "-"
        journey_date_str = "-"
        if start_display:
            try:
                dt = datetime.strptime(start_display, "%Y-%m-%d %H:%M:%S")
                start_time_str = dt.strftime("%d-%m-%Y %H:%M:%S")
                journey_date_str = dt.strftime("%d-%m-%Y")
            except Exception:
                start_time_str = start_display
                journey_date_str = start_display.split(" ")[0] if " " in start_display else start_display

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

        # Format Time Ago (e.g. 4 h, 1 d, 1 w). Datetime columns in this
        # deployment are stored as system-zone wall time (including Frappe's
        # own creation/modified), so the diff is taken against local now.
        time_ago = "-"
        if j.creation:
            try:
                c_dt = _parse_dt(j.creation)
                if c_dt is not None and c_dt.tzinfo is None:
                    diff = datetime.now() - c_dt
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

    # Journey actual start/end are stored in the storage timezone (system
    # zone wall time) - display as stored, expose the aware UTC instant too.
    start_utc, start_display = _journey_dt_to_utc(doc.start_time)
    start_time_str = start_display or "N/A"
    timeline_events.append({
        "timestamp": start_time_str,
        "timestamp_utc": start_utc.isoformat().replace("+00:00", "Z") if start_utc else None,
        "type": "TRIP_START",
        "title": "Trip Started",
        "details": f"Started at {doc.start_location or 'Initial Location'}",
        "icon": "fa-play-circle"
    })

    # Trip Health Log (10s device status log from the phone)
    # Decoded for timeline connection events and telemetry only; the full log
    # and its summary are server-side data and are NOT sent to the client page.
    health_entries = _decode_trip_status_log(getattr(doc, "trip_status_log", None))

    # User Offline / User Online events merged from BOTH the health log and
    # the legacy telemetry network_events, deduplicated per transition.
    connection_events = _merged_connection_events(health_entries, meta)

    timeline_events.extend(connection_events)

    # Device & Telemetry card payload (merged from health log + metadata)
    telemetry = _build_device_telemetry(meta, health_entries, raw_gps)

    end_utc, end_display = _journey_dt_to_utc(doc.end_time)
    end_time_str = end_display or "In Progress"

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

    resolved_end_location = doc.end_location or meta.get("end_address") or meta.get("destination_address") or _app_journey_metadata(meta).get("end_address")
    if not resolved_end_location or resolved_end_location == "N/A":
        if raw_gps and len(raw_gps) > 0:
            last_pt = raw_gps[-1]
            lat = last_pt.get("latitude") or last_pt.get("lat")
            lng = last_pt.get("longitude") or last_pt.get("lng") or last_pt.get("lon")
            if lat and lng:
                resolved_end_location = f"{lat}, {lng}"

    if doc.status == "Completed":
        timeline_events.append({
            "timestamp": end_display or "",
            "timestamp_utc": end_utc.isoformat().replace("+00:00", "Z") if end_utc else None,
            "type": "TRIP_END",
            "title": "Trip Ended",
            "details": f"Ended at {resolved_end_location or 'Final Location'}",
            # End reason is part of the Trip Ended event (not a separate
            # timeline item). Rendered as a second line by the page JS.
            "reason": human_end_reason if human_end_reason else None,
            "icon": "fa-flag-checkered"
        })

    # Chronological order by numeric instant, never by formatted string.
    # Tie order: Trip Start -> connectivity events in capture order -> End;
    # events without a usable instant keep their original relative order
    # after all timed events instead of being shuffled by display text.
    _category_order = {"TRIP_START": 0, "TRIP_END": 2}

    def _timeline_sort_key(indexed):
        _, ev = indexed
        ts = ev.get("timestamp_utc")
        instant = None
        if ts:
            dt = _parse_dt(ts)
            instant = dt.timestamp() if dt else None
        if instant is None:
            return (1, 0.0, 1, indexed[0])
        return (0, instant, _category_order.get(ev.get("type"), 1), indexed[0])

    timeline_events.sort(key=_timeline_sort_key)

    start_odo = getattr(doc, "start_odometer", None) or meta.get("start_odometer")
    end_odo = getattr(doc, "end_odometer", None) or meta.get("end_odometer")
    start_n = getattr(doc, "start_notes", None) or meta.get("start_notes")
    end_n = getattr(doc, "end_notes", None) or meta.get("end_notes")
    calc_odo_dist = getattr(doc, "calculated_odometer_distance", None) or meta.get("calculated_odometer_distance")

    return {
        "trip_id": doc.name,
        "flutter_journey_id": getattr(doc, "flutter_journey_id", None),
        "employee_id": doc.employee,
        "employee_name": employee_name,
        "status": doc.status,
        "journey_date": start_time_str.split(" ")[0] if doc.start_time else "",
        "start_time": start_time_str,
        "end_time": end_time_str,
        "start_time_utc": start_utc.isoformat().replace("+00:00", "Z") if start_utc else None,
        "end_time_utc": end_utc.isoformat().replace("+00:00", "Z") if end_utc else None,
        "start_location": doc.start_location or "N/A",
        "end_location": resolved_end_location or "N/A",
        "distance_km": doc.distance_km or 0.0,
        "duration_seconds": getattr(doc, "duration_seconds", None) or 0,
        "end_reason": human_end_reason,
        "start_odometer": start_odo,
        "end_odometer": end_odo,
        "start_notes": start_n,
        "end_notes": end_n,
        "calculated_odometer_distance": calc_odo_dist,
        "start_odometer_photo": getattr(doc, "start_odometer_photo", None) or meta.get("start_odometer_photo"),
        "end_odometer_photo": getattr(doc, "end_odometer_photo", None) or meta.get("end_odometer_photo"),
        "raw_gps_data": raw_gps,
        "telemetry": telemetry,
        "timeline_events": timeline_events
    }
