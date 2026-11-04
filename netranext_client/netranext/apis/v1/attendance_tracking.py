"""
Attendance-based automatic trip tracking - tenant bench state machine.

Called by the central Service bench over the integration-token sync channel
(same trust boundary as sync.py). Owns the session/requirement/evidence/event
documents introduced by AUTO_ATTENDANCE_TRIP_IMPLEMENTATION_PLAN.md:

- NetraNext Attendance Trip Session: one per attendance check-in while the
  tenant setting is enabled. Never created when disabled.
- NetraNext Trip Odometer Requirement: start/end odometer evidence
  requirements (only when "Enable Odometer Reading" is also on).
- NetraNext Trip Odometer Evidence: photo + OCR + chronology validation.
- NetraNext Attendance Trip Event: idempotent, append-only client events.

Key invariants enforced here (server-side):
- A trip is only auto-started after validated genuine movement, and only
  when no manual/scheduled trip is active for the employee (one collector).
- A late odometer photo NEVER auto-populates the journey reading; it goes
  to reviewer validation (late_under_review).
- The journey Expense Claim draft is only created once every required
  evidence is satisfied (finance gate in netranext_journey.py).
- Check-in/out flow and manual trips are untouched when the tenant setting
  is disabled.
"""
import hashlib
import json
import uuid
from datetime import timedelta

import frappe
from frappe.utils import flt, get_datetime, now_datetime, nowdate

from netranext_client.netranext.utils.logger import tenant_bench_logger
from netranext_client.netranext.utils.response_formatter import (
    create_success_response,
)
from netranext_client.netranext.utils.error_handler import handle_api_exception
from netranext_client.netranext.utils.movement_validation import (
    evaluate_movement,
)

# --- Policy constants (plan sections 5, 6, 7, 13 + approved decisions) ------
OFFLINE_LEASE_HOURS = 4                # bounded offline lease for event replay
PRE_DEPARTURE_FRESHNESS_MIN = 30       # approved: photo within 30 min before departure
END_EVIDENCE_FRESHNESS_MIN = 60        # end photo within 60 min after checkout
EVIDENCE_GRACE_MIN = 15                # requirement becomes due this long after departure
EVIDENCE_REMINDER_INTERVAL_MIN = 15    # reminder cadence while requirement pending
EVIDENCE_REMINDER_MAX = 2              # max odometer reminders per requirement
CHECKOUT_REMINDER_DELAY_MIN = 60       # approved: start 1h after shift end
CHECKOUT_REMINDER_INTERVAL_MIN = 60    # approved: repeat hourly until checkout
CHECKOUT_REMINDER_RELEVANCE_H = 12     # stop scheduling after this many hours past shift end
REQUIREMENT_RELEVANCE_MIN = 120        # stop scheduling start reminders 2h after departure
SHIFT_FALLBACK_HOURS = 9               # assumed shift length when no shift is assigned

SETTING_FIELD = "enable_auto_attendance_trip_tracking"


# ---------------------------------------------------------------------------
# Settings / helpers
# ---------------------------------------------------------------------------

def _auto_tracking_enabled():
    """Tenant setting gate. Every public path re-checks this."""
    try:
        return bool(
            frappe.db.get_single_value("NetraNext Settings", SETTING_FIELD)
        )
    except Exception:
        return False


def _odometer_required():
    try:
        return bool(
            frappe.db.get_single_value("NetraNext Settings", "enable_odometer_reading")
        )
    except Exception:
        return False


def _manual_odometer_allowed():
    try:
        return bool(frappe.db.get_single_value(
            "NetraNext Settings", "allow_manual_odometer_edit"))
    except Exception:
        return True


def _get_active_session(employee_id):
    """The employee's open session (at most one by construction)."""
    return frappe.db.get_value(
        "NetraNext Attendance Trip Session",
        {"employee": employee_id,
         "status": ["in", ["monitoring", "trip_active"]]},
        "name",
    )


def _resolve_shift_ends_at(employee_id, checkin_time):
    """Best-effort shift end for the checkout-reminder schedule.

    Uses the active Shift Assignment's Shift Type end time when available;
    falls back to check-in + 9h so employees without formal shift
    assignments still receive reminders.
    """
    try:
        assignment = frappe.db.get_value(
            "Shift Assignment",
            {"employee": employee_id, "status": "Active", "docstatus": 1,
             "start_date": ["<=", nowdate()]},
            "shift_type",
        )
        if assignment:
            end_time_str = frappe.db.get_value(
                "Shift Type", assignment, "end_time"
            )
            if end_time_str:
                base = get_datetime(checkin_time)
                shift_end = base.replace(
                    hour=int(str(end_time_str)[:2]),
                    minute=int(str(end_time_str)[3:5]),
                    second=0,
                )
                # Overnight shifts: end time earlier than start means +1 day.
                if shift_end < base:
                    shift_end += timedelta(days=1)
                return shift_end
    except Exception as exc:
        tenant_bench_logger.warning(
            f"Shift resolution failed for {employee_id}: {exc}", "ATT_TRIP"
        )
    return get_datetime(checkin_time) + timedelta(hours=SHIFT_FALLBACK_HOURS)


def _session_payload(session_or_name):
    """Serialization of a session + its requirements for mobile/dashboard.

    Accepts either the primary-key string or an already-loaded session doc
    (avoids a redundant fetch right after insert/save).
    """
    if isinstance(session_or_name, str):
        session_name = session_or_name
        session = frappe.get_doc("NetraNext Attendance Trip Session", session_name)
    else:
        session = session_or_name
        session_name = session.name
    requirements = frappe.db.get_all(
        "NetraNext Trip Odometer Requirement",
        filters={"session": session_name},
        fields=["kind", "status", "late", "due_at", "window_ends_at",
                "reminders_sent", "reading_value", "name"],
    )
    return {
        "session_id": session.session_id,
        "session_name": session.name,
        "employee": session.employee,
        "user_id": session.user_id,
        "status": session.status,
        "monitor_state": session.monitor_state,
        "checkin_name": session.checkin_name,
        "checkin_time": str(session.checkin_time) if session.checkin_time else None,
        # Movement anchor for the mobile monitor (app-restart resume): the
        # Dart validator mirrors movement_validation.py against these.
        "checkin_latitude": session.checkin_latitude,
        "checkin_longitude": session.checkin_longitude,
        "checkin_accuracy": session.checkin_accuracy,
        "checkout_time": str(session.checkout_time) if session.checkout_time else None,
        "shift_ends_at": str(session.shift_ends_at) if session.shift_ends_at else None,
        "reserved_journey_id": session.reserved_journey_id,
        "journey": session.journey,
        "movement_confirmed_at": str(session.movement_confirmed_at)
        if session.movement_confirmed_at else None,
        "observed_start_at": str(session.observed_start_at)
        if session.observed_start_at else None,
        "observed_end_at": str(session.observed_end_at)
        if session.observed_end_at else None,
        "departure_detected_at": str(session.departure_detected_at)
        if session.departure_detected_at else None,
        "ownership_conflict": bool(session.ownership_conflict),
        "conflict_reason": session.conflict_reason,
        "evidence_state": session.evidence_state,
        "odometer_required": bool(session.odometer_required),
        "offline_lease_until": str(session.offline_lease_until)
        if session.offline_lease_until else None,
        "requirements": [
            {
                "kind": r.kind,
                "status": r.status,
                "late": bool(r.late),
                "due_at": str(r.due_at) if r.due_at else None,
                "reminders_sent": r.reminders_sent or 0,
                "reading_value": r.reading_value,
            }
            for r in requirements
        ],
    }


def _record_event(session, event_type, payload=None, processing_status="applied",
                  result_note=None, occurred_at=None, event_id=None,
                  employee=None):
    """Append-only event log (idempotent on event_id)."""
    event_id = event_id or str(uuid.uuid4())
    if frappe.db.exists("NetraNext Attendance Trip Event", {"event_id": event_id}):
        return None
    session_name = session.name if hasattr(session, "name") else session
    doc = frappe.get_doc({
        "doctype": "NetraNext Attendance Trip Event",
        "event_id": event_id,
        "session": session_name,
        "session_id": session.session_id if hasattr(session, "session_id") else None,
        "employee": employee
        or (session.employee if hasattr(session, "employee") else None),
        "event_type": event_type,
        "occurred_at": occurred_at or now_datetime(),
        "received_at": now_datetime(),
        "processing_status": processing_status,
        "payload": json.dumps(payload or {}, default=str),
        "result_note": result_note,
    })
    doc.insert(ignore_permissions=True)
    return doc.name


def _refresh_evidence_state(session):
    """Recompute the aggregated dashboard evidence_state from requirements."""
    if not session.odometer_required:
        session.evidence_state = "not_required"
        return
    reqs = frappe.get_all(
        "NetraNext Trip Odometer Requirement",
        filters={"session": session.name},
        fields=["kind", "status"],
    )
    by_kind = {r.kind: r for r in reqs}
    start = by_kind.get("start")
    end = by_kind.get("end")

    if start and start.status == "exception_requested":
        session.evidence_state = "exception_requested"
    elif start and start.status == "late_under_review":
        session.evidence_state = "late_evidence_review"
    elif start and start.status == "satisfied":
        if end and end.status == "pending":
            session.evidence_state = "pending_end"
        elif end and end.status == "late_under_review":
            session.evidence_state = "late_evidence_review"
        elif end and end.status == "exception_requested":
            session.evidence_state = "exception_requested"
        else:
            session.evidence_state = "satisfied_predeparture"
    elif start and start.status == "pending":
        session.evidence_state = "pending_predeparture"
    elif not start:
        session.evidence_state = "not_required"


def _finance_status_for(session):
    """Eligibility for Draft Expense Claim creation (plan section 13).

    Odometer-first (approved decision): eligible only when every required
    odometer reading is validated. Late evidence under review blocks the
    claim until a reviewer resolves it.
    """
    if not session.odometer_required:
        return "eligible"
    reqs = frappe.get_all(
        "NetraNext Trip Odometer Requirement",
        filters={"session": session.name},
        fields=["status"],
    )
    blocking = [
        r for r in reqs
        if r.status in ("pending", "late_under_review", "exception_requested")
    ]
    return "blocked_pending_evidence" if blocking else "eligible"


def _ms_to_datetime(ms):
    if ms is None:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc)\
            .astimezone().replace(tzinfo=None)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Check-in / check-out hooks (called from sync.store_attendance)
# ---------------------------------------------------------------------------

def handle_checkin_stored(att_data, checkin_name):
    """After a successful IN check-in: open the tracking session.

    Returns the attendance_tracking payload embedded in the store_attendance
    response (session id + reserved journey id + requirements), or None when
    the tenant setting is disabled (existing behaviour untouched).
    """
    if not _auto_tracking_enabled():
        return None

    employee_id = att_data.get("employee_id")
    log_type = (att_data.get("log_type") or "").upper()
    if log_type != "IN" or not employee_id:
        return None

    session_id = att_data.get("tracking_session_id")
    if session_id and frappe.db.exists(
            "NetraNext Attendance Trip Session", {"session_id": session_id}):
        # Duplicate IN replay: return the existing session untouched.
        payload = _session_payload(frappe.db.get_value(
            "NetraNext Attendance Trip Session",
            {"session_id": session_id}, "name"))
        payload["enabled"] = True
        return payload

    # One open session per employee: a stale session from an earlier
    # check-in is cancelled before a new one opens.
    stale = _get_active_session(employee_id)
    if stale:
        stale_doc = frappe.get_doc("NetraNext Attendance Trip Session", stale)
        stale_doc.status = "cancelled"
        stale_doc.cancellation_reason = "Superseded by a new check-in"
        stale_doc.monitor_state = "ended"
        stale_doc.save(ignore_permissions=True)

    session_id = session_id or f"ats-{uuid.uuid4()}"
    odometer_required = _odometer_required()
    checkin_time = get_datetime(att_data.get("time") or now_datetime())
    accuracy = att_data.get("tracking_accuracy")
    if accuracy is not None:
        try:
            accuracy = float(accuracy)
        except (TypeError, ValueError):
            accuracy = None
    # Group attendance is stored by one login for many employees; the
    # session's notification target must be the employee's own user.
    user_id = att_data.get("user_id")
    if not user_id:
        try:
            user_id = frappe.db.get_value("Employee", employee_id, "user_id")
        except Exception:
            user_id = None

    session = frappe.get_doc({
        "doctype": "NetraNext Attendance Trip Session",
        "session_id": session_id,
        "employee": employee_id,
        "user_id": user_id,
        "status": "monitoring",
        "monitor_state": "awaiting_movement",
        "checkin_name": checkin_name,
        "checkin_time": checkin_time,
        "checkin_latitude": att_data.get("latitude"),
        "checkin_longitude": att_data.get("longitude"),
        "checkin_accuracy": accuracy,
        "auto_start_snapshot": 1,
        "odometer_required": 1 if odometer_required else 0,
        "reserved_journey_id": f"auto-{uuid.uuid4()}",
        "offline_lease_until": now_datetime() + timedelta(hours=OFFLINE_LEASE_HOURS),
        "shift_ends_at": _resolve_shift_ends_at(employee_id, checkin_time),
        "evidence_state": "pending_predeparture" if odometer_required
        else "not_required",
    })
    session.insert(ignore_permissions=True)

    if odometer_required:
        frappe.get_doc({
            "doctype": "NetraNext Trip Odometer Requirement",
            "requirement_key": f"{session_id}:start",
            "session": session.name,
            "kind": "start",
            "status": "pending",
        }).insert(ignore_permissions=True)

    _record_event(
        session, "session_started",
        payload={"checkin_name": checkin_name, "log_type": "IN",
                 "latitude": att_data.get("latitude"),
                 "longitude": att_data.get("longitude")},
        occurred_at=checkin_time,
    )
    tenant_bench_logger.info(
        f"Attendance trip session {session.name} opened for {employee_id}",
        "ATT_TRIP",
    )
    payload = _session_payload(session)
    # The mobile bloc treats a missing 'enabled' key as disabled — the
    # check-in response must be self-sufficient (it only exists when the
    # tenant setting is on, so True is always correct here).
    payload["enabled"] = True
    return payload


def handle_checkout_stored(att_data, checkin_name):
    """After a successful OUT check-in: end the trip + session.

    Missing end odometer evidence stays visible as a pending requirement
    ("Trip End Odometer Photo Pending"); the claim stays blocked.
    """
    if not _auto_tracking_enabled():
        return None

    employee_id = att_data.get("employee_id")
    log_type = (att_data.get("log_type") or "").upper()
    if log_type != "OUT" or not employee_id:
        return None

    session_name = _get_active_session(employee_id)
    if not session_name:
        return None

    session = frappe.get_doc("NetraNext Attendance Trip Session", session_name)
    checkout_time = get_datetime(att_data.get("time") or now_datetime())
    session.checkout_name = checkin_name
    session.checkout_time = checkout_time
    session.monitor_state = "ended"
    session.status = "completed"
    session.observed_end_at = checkout_time

    if session.journey:
        if session.odometer_required:
            # End requirement FIRST: the finance recomputation below must
            # see it, or the claim would be released prematurely.
            frappe.get_doc({
                "doctype": "NetraNext Trip Odometer Requirement",
                "requirement_key": f"{session.session_id}:end",
                "session": session.name,
                "kind": "end",
                "status": "pending",
                "due_at": checkout_time + timedelta(minutes=EVIDENCE_GRACE_MIN),
            }).insert(ignore_permissions=True)
            session.evidence_state = "pending_end"

        journey = frappe.get_doc("NetraNext Journey", session.journey)
        journey.status = "Completed"
        journey.end_time = checkout_time
        journey.collection_state = "completed"
        journey.observed_end_at = checkout_time
        journey.evidence_status = "pending_end" if session.odometer_required \
            else "not_required"
        _apply_validated_readings(session, journey)
        journey.finance_status = _finance_status_for(session)
        journey.save(ignore_permissions=True)
        _record_event(
            session, "trip_auto_stopped",
            payload={"reason": "attendance_checkout", "journey": journey.name},
            occurred_at=checkout_time,
        )
        _release_claim_when_eligible(session, journey)
    else:
        # No genuine movement ever happened: no trip, no claim. A still
        # pending start requirement is moot - nothing was driven.
        frappe.db.set_value(
            "NetraNext Trip Odometer Requirement",
            {"session": session.name, "kind": "start", "status": "pending"},
            {"status": "not_required"},
        )
        session.evidence_state = "not_required"

    session.save(ignore_permissions=True)
    _record_event(
        session, "session_ended",
        payload={"checkin_name": checkin_name, "log_type": "OUT"},
        occurred_at=checkout_time,
    )
    tenant_bench_logger.info(
        f"Attendance trip session {session.name} closed at checkout "
        f"(journey={session.journey})",
        "ATT_TRIP",
    )
    payload = _session_payload(session)
    payload["enabled"] = True
    return payload


def _apply_validated_readings(session, journey):
    """Copy SATISFIED requirement readings onto the journey fields.

    Only satisfied requirements (on-time or reviewer-validated) ever reach
    the journey - a late photo never auto-populates the reading.
    """
    for kind, odometer_field in (("start", "start_odometer"),
                                 ("end", "end_odometer")):
        row = frappe.db.get_value(
            "NetraNext Trip Odometer Requirement",
            {"session": session.name, "kind": kind},
            ["status", "reading_value"], as_dict=True,
        )
        if row and row.status == "satisfied" and row.reading_value is not None:
            setattr(journey, odometer_field, flt(row.reading_value))
    if (journey.start_odometer is not None and journey.end_odometer is not None
            and flt(journey.end_odometer) >= flt(journey.start_odometer)):
        journey.calculated_odometer_distance = (
            flt(journey.end_odometer) - flt(journey.start_odometer))
        journey.financial_distance_basis = "odometer"


def _release_claim_when_eligible(session, journey):
    """Create the Draft Expense Claim once every requirement is satisfied.

    The journey's on_update hook also guards this; evidence can complete
    long after the last journey save, so this path releases the claim from
    the evidence side. Claim creation itself is an idempotent upsert.
    """
    if journey.status != "Completed":
        return
    if _finance_status_for(session) != "eligible":
        return
    from netranext_client.netranext.doctype.netranext_journey.netranext_journey import (
        create_expense_claim_for_journey,
    )
    try:
        create_expense_claim_for_journey(journey)
        if journey.finance_status != "claim_created":
            journey.finance_status = "claim_created"
            journey.save(ignore_permissions=True)
    except Exception as exc:
        tenant_bench_logger.error(
            f"Expense claim creation failed for {journey.name}: {exc}",
            "ATT_TRIP",
        )


# ---------------------------------------------------------------------------
# Movement confirmation / auto trip start
# ---------------------------------------------------------------------------

def _active_conflict_journey(employee_id):
    """Any live manual/scheduled trip that forbids an auto start."""
    return frappe.db.get_value(
        "NetraNext Journey",
        {"employee": employee_id,
         "status": "In Progress",
         "tracking_source": ["in", ["manual", "scheduled", None, ""]]},
        "name",
    )


def _auto_start_journey(session, event):
    """Create the In Progress journey for a validated movement confirmation.

    Uses the session's reserved journey id as flutter_journey_id so the
    mobile's subsequent store_journey syncs (and offline replays) match by
    branch 1 (journey id) and never fall into legacy merge/force-complete
    fallbacks.
    """
    anchor = {
        "latitude": session.checkin_latitude,
        "longitude": session.checkin_longitude,
        "accuracy": session.checkin_accuracy,
        "timestamp": event.get("anchor_timestamp_ms"),
    }
    fixes = event.get("fixes") or []
    verdict = evaluate_movement(anchor, fixes, now_ms=None)
    if verdict["status"] != "confirmed":
        return None, "movement_not_confirmed_by_server", verdict

    observed_start = _ms_to_datetime(
        event.get("observed_start_at_ms") or verdict["confirmed_at_ms"]
    ) or now_datetime()

    journey = frappe.get_doc({
        "doctype": "NetraNext Journey",
        "employee": session.employee,
        "user_id": session.user_id,
        "journey_date": observed_start.date(),
        "start_time": observed_start,
        "status": "In Progress",
        "flutter_journey_id": session.reserved_journey_id,
        "journey_name": "Attendance Trip",
        "tracking_source": "attendance_auto",
        "attendance_session": session.name,
        "collection_state": "active",
        "evidence_status": "pending_predeparture"
        if session.odometer_required else "not_required",
        "finance_status": _finance_status_for(session),
        "financial_distance_basis": "odometer"
        if session.odometer_required else "gps",
        "observed_start_at": observed_start,
        "departure_detected_at": observed_start,
        "metadata": {
            "auto_start": {
                "session_id": session.session_id,
                "qualifying_fixes": verdict["qualifying"],
                "max_displacement_m": verdict["max_displacement_m"],
                "anchor": {
                    "latitude": session.checkin_latitude,
                    "longitude": session.checkin_longitude,
                    "accuracy": session.checkin_accuracy,
                },
            }
        },
    })
    journey.insert(ignore_permissions=True)
    return journey, None, verdict


def _apply_movement_confirmed(session, event):
    """Idempotent transition monitoring -> trip_active."""
    if session.status == "trip_active":
        return {"already_started": True, "journey": session.journey,
                "reserved_journey_id": session.reserved_journey_id}

    if session.status != "monitoring":
        return {"ignored": True, "reason": f"session_{session.status}"}

    conflict = _active_conflict_journey(session.employee)
    if conflict:
        session.ownership_conflict = 1
        session.conflict_reason = (
            f"Manual/scheduled trip {conflict} already In Progress; "
            "automatic trip suppressed"
        )
        session.monitor_state = "suspended_conflict"
        _refresh_evidence_state(session)
        session.save(ignore_permissions=True)
        _record_event(
            session, "ownership_conflict",
            payload={"conflict_journey": conflict},
        )
        return {"ownership_conflict": True, "conflict_journey": conflict}

    journey, error, verdict = _auto_start_journey(session, event)
    if error:
        _record_event(session, "movement_detected", payload={
            "rejected": error,
            "max_displacement_m": verdict.get("max_displacement_m"),
        })
        return {"rejected": error}

    confirmed_at = _ms_to_datetime(event.get("occurred_at_ms")) or now_datetime()
    departure = journey.observed_start_at or confirmed_at
    session.status = "trip_active"
    session.monitor_state = "movement_confirmed"
    session.journey = journey.name
    session.movement_confirmed_at = confirmed_at
    session.observed_start_at = departure
    session.departure_detected_at = departure
    _refresh_evidence_state(session)
    session.save(ignore_permissions=True)

    # Start requirement becomes due a grace period after departure.
    if session.odometer_required:
        frappe.db.set_value(
            "NetraNext Trip Odometer Requirement",
            {"session": session.name, "kind": "start", "status": "pending"},
            {"due_at": departure + timedelta(minutes=EVIDENCE_GRACE_MIN),
             "window_ends_at": departure},
        )

    _record_event(
        session, "trip_auto_started",
        payload={"journey": journey.name,
                 "reserved_journey_id": session.reserved_journey_id,
                 "observed_start_at": str(departure)},
        occurred_at=confirmed_at,
    )
    tenant_bench_logger.info(
        f"Auto trip {journey.name} started for session {session.name}",
        "ATT_TRIP",
    )
    return {
        "trip_started": True,
        "journey": journey.name,
        "reserved_journey_id": session.reserved_journey_id,
        "observed_start_at": str(departure),
    }


# ---------------------------------------------------------------------------
# Public API (Service bench -> here, integration-token authenticated)
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def get_session_state(employee_id=None, session_id=None):
    """Current session state for the mobile dashboard card."""
    try:
        from netranext_client.netranext.apis.v1.sync import validate_sync_request
        validate_sync_request()

        if session_id:
            name = frappe.db.get_value(
                "NetraNext Attendance Trip Session",
                {"session_id": session_id}, "name",
            )
        elif employee_id:
            name = _get_active_session(employee_id)
            if not name:
                # Fall back to the most recent session: post-checkout
                # pending evidence still needs to show on the dashboard.
                name = frappe.db.get_value(
                    "NetraNext Attendance Trip Session",
                    {"employee": employee_id}, "name",
                    order_by="creation desc",
                )
        else:
            name = None

        if not name:
            return create_success_response(
                message="No attendance trip session",
                data={"session": None, "enabled": _auto_tracking_enabled()},
            )
        payload = _session_payload(name)
        payload["enabled"] = _auto_tracking_enabled()
        return create_success_response(
            message="Session state", data={"session": payload}
        )
    except Exception as e:
        return handle_api_exception(e, "ATT_TRIP")


@frappe.whitelist(allow_guest=True)
def submit_events(events):
    """Idempotent client-event ingestion (movement confirmations etc.).

    events: list of {event_id, session_id, employee_id, event_type,
    occurred_at_ms, client_seq, payload}. Movement validation runs again
    server-side with the shared validator before any trip is created.
    """
    try:
        from netranext_client.netranext.apis.v1.sync import validate_sync_request
        validate_sync_request()

        if isinstance(events, str):
            events = json.loads(events)
        if not isinstance(events, list):
            events = [events]

        if not _auto_tracking_enabled():
            return create_success_response(
                message="Automatic attendance trip tracking disabled",
                data={"enabled": False, "results": []},
            )

        results = []
        for event in events:
            try:
                results.append(_apply_event(event))
            except Exception as item_exc:
                tenant_bench_logger.error(
                    f"Event failed: {item_exc}", "ATT_TRIP"
                )
                frappe.log_error(frappe.get_traceback(),
                                 "Attendance Tracking Event Exception")
                results.append({
                    "event_id": (event or {}).get("event_id"),
                    "status": "error",
                    "error": str(item_exc),
                })
        return create_success_response(
            message="Events processed", data={"results": results}
        )
    except Exception as e:
        return handle_api_exception(e, "ATT_TRIP")


def _apply_event(event):
    event_id = event.get("event_id")
    event_type = event.get("event_type")
    session_id = event.get("session_id")

    if not event_type:
        return {"status": "ignored", "reason": "missing event_type"}

    if not session_id:
        return {"event_id": event_id, "status": "ignored",
                "reason": "missing session_id"}

    session_name = frappe.db.get_value(
        "NetraNext Attendance Trip Session", {"session_id": session_id}, "name"
    )
    if not session_name:
        return {"event_id": event_id, "status": "ignored",
                "reason": "unknown_session"}

    session = frappe.get_doc("NetraNext Attendance Trip Session", session_name)

    if event_type == "movement_confirmed":
        existing = frappe.db.get_value(
            "NetraNext Attendance Trip Event",
            {"event_id": event_id}, ["processing_status", "result_note"],
            as_dict=True,
        ) if event_id else None
        if existing and existing.processing_status == "applied":
            outcome = json.loads(existing.result_note or "{}")
            outcome["event_id"] = event_id
            outcome["duplicate"] = True
            return outcome
        outcome = _apply_movement_confirmed(session, event)
        outcome["event_id"] = event_id
        _record_event(
            session, "movement_confirmed", payload=event,
            occurred_at=_ms_to_datetime(event.get("occurred_at_ms")),
            event_id=event_id,
            processing_status="applied",
            result_note=json.dumps(outcome, default=str),
        )
        return outcome

    if event_type == "drift_filtered":
        _record_event(
            session, "drift_filtered", payload=event,
            occurred_at=_ms_to_datetime(event.get("occurred_at_ms")),
            event_id=event_id,
        )
        return {"event_id": event_id, "status": "recorded"}

    if event_type == "monitor_suspended":
        if session.monitor_state != "ended":
            session.monitor_state = "suspended_conflict"
            if event.get("reason"):
                session.conflict_reason = event.get("reason")
            session.save(ignore_permissions=True)
        _record_event(session, "monitor_suspended", payload=event,
                      event_id=event_id)
        return {"event_id": event_id, "status": "recorded"}

    if event_type == "offline_reconciled":
        _record_event(session, "offline_reconciled", payload=event,
                      event_id=event_id)
        return {"event_id": event_id, "status": "recorded"}

    _record_event(session, event_type, payload=event, event_id=event_id,
                  processing_status="ignored", result_note="unhandled type")
    return {"event_id": event_id, "status": "ignored",
            "reason": "unhandled event_type"}


@frappe.whitelist(allow_guest=True)
def store_odometer_evidence(evidence_data):
    """Store one odometer photo + OCR outcome against a requirement.

    evidence_data: {evidence_id, session_id, kind, employee_id,
    photo_base64, photo_hash, client_captured_at_ms,
    exif_captured_at_ms?, ocr: {status, value, raw_text, request_id},
    source, reading_value (manual entry when allowed)}.

    Chronology (approved 30-minute freshness window):
    - start kind BEFORE departure  -> satisfied (on time).
    - start kind AFTER departure   -> recorded, late_under_review; the
      journey reading is never auto-populated from it.
    - OCR failure with manual entry disabled -> needs retake (requirement
      stays pending, reminders continue).
    """
    try:
        from netranext_client.netranext.apis.v1.sync import validate_sync_request
        validate_sync_request()

        if isinstance(evidence_data, str):
            evidence_data = json.loads(evidence_data)

        session_id = evidence_data.get("session_id")
        kind = evidence_data.get("kind")
        if not session_id or kind not in ("start", "end"):
            return create_success_response(
                message="session_id and kind (start|end) are required",
                data={"status": "error", "reason": "invalid_request"},
            )

        session_name = frappe.db.get_value(
            "NetraNext Attendance Trip Session", {"session_id": session_id},
            "name",
        )
        if not session_name:
            return create_success_response(
                message="Unknown session",
                data={"status": "error", "reason": "unknown_session"},
            )
        session = frappe.get_doc("NetraNext Attendance Trip Session", session_name)

        # Idempotent replay of the same evidence upload.
        evidence_id = evidence_data.get("evidence_id")
        if evidence_id and frappe.db.exists(
            "NetraNext Trip Odometer Evidence", {"evidence_id": evidence_id}
        ):
            prior = frappe.db.get_value(
                "NetraNext Trip Odometer Evidence",
                {"evidence_id": evidence_id}, ["name", "status"], as_dict=True,
            )
            return create_success_response(
                message="Evidence already stored",
                data={"status": "duplicate", "evidence": prior.name,
                      "evidence_status": prior.status},
            )

        requirement = frappe.db.get_value(
            "NetraNext Trip Odometer Requirement",
            {"session": session.name, "kind": kind}, "name",
        )
        if not requirement:
            frappe.get_doc({
                "doctype": "NetraNext Trip Odometer Requirement",
                "requirement_key": f"{session_id}:{kind}",
                "session": session.name,
                "kind": kind,
                "status": "pending",
            }).insert(ignore_permissions=True)
            requirement = frappe.db.get_value(
                "NetraNext Trip Odometer Requirement",
                {"session": session.name, "kind": kind}, "name",
            )

        ocr = evidence_data.get("ocr") or {}
        ocr_status = ocr.get("status") or "skipped"
        ocr_value = ocr.get("value")
        manual_allowed = _manual_odometer_allowed()
        source = evidence_data.get("source") or (
            "detected" if ocr_status == "detected" else "manual"
        )

        proposed_value = ocr_value if ocr_status == "detected" else (
            evidence_data.get("reading_value")
            if source == "manual" and manual_allowed else None
        )

        # --- Chronology validation -------------------------------------------
        capture_ms = evidence_data.get("exif_captured_at_ms") or \
            evidence_data.get("client_captured_at_ms")
        capture_dt = _ms_to_datetime(capture_ms)
        reference = session.observed_start_at if kind == "start" \
            else (session.observed_end_at or session.checkout_time)

        fresh = None
        margin_s = None
        if capture_dt and kind == "start":
            if reference:
                # Photo must predate departure by at most the freshness
                # window, and must not predate the check-in by >5 min.
                margin_s = int((reference - capture_dt).total_seconds())
                fresh = (-300 <= margin_s
                         and margin_s <= PRE_DEPARTURE_FRESHNESS_MIN * 60)
            else:
                # Pre-departure upload before any movement: on time.
                fresh = True
        elif capture_dt and kind == "end":
            if reference:
                delta_s = int((capture_dt - reference).total_seconds())
                margin_s = delta_s
                fresh = -300 <= delta_s <= END_EVIDENCE_FRESHNESS_MIN * 60
            else:
                fresh = True
        late = fresh is False

        # --- Persist the evidence ---------------------------------------------
        evidence = frappe.get_doc({
            "doctype": "NetraNext Trip Odometer Evidence",
            "evidence_id": evidence_id or f"evd-{uuid.uuid4()}",
            "session": session.name,
            "requirement": requirement,
            "employee": session.employee,
            "journey": session.journey,
            "kind": kind,
            "status": "uploaded",
            "photo_hash": evidence_data.get("photo_hash"),
            "client_captured_at": _ms_to_datetime(
                evidence_data.get("client_captured_at_ms")),
            "exif_captured_at": _ms_to_datetime(
                evidence_data.get("exif_captured_at_ms")),
            "received_at": now_datetime(),
            "capture_channel": "late" if late else (
                "dashboard_pending" if reference else "pre_departure"),
            "freshness_valid": 1 if fresh else 0,
            "freshness_margin_seconds": margin_s,
            "ocr_status": ocr_status,
            "ocr_value": ocr_value,
            "ocr_raw_text": ocr.get("raw_text"),
            "ocr_request_id": ocr.get("request_id"),
            "reading_value": flt(proposed_value)
            if proposed_value is not None else None,
            "source": source,
        })

        photo_base64 = evidence_data.get("photo_base64")
        if photo_base64:
            import base64
            from frappe.utils.file_manager import save_file
            content = base64.b64decode(photo_base64)
            if evidence_data.get("photo_hash"):
                digest = hashlib.sha256(content).hexdigest()
                if digest != evidence_data.get("photo_hash"):
                    return create_success_response(
                        message="Photo hash mismatch",
                        data={"status": "error", "reason": "hash_mismatch"},
                    )
            evidence.insert(ignore_permissions=True)
            file_doc = save_file(
                fname=f"odometer_{kind}_{evidence.evidence_id}.jpg",
                content=content,
                dt="NetraNext Trip Odometer Evidence",
                dn=evidence.name,
                is_private=1,
            )
            evidence.photo_file = file_doc.file_url
            evidence.save(ignore_permissions=True)
        else:
            evidence.insert(ignore_permissions=True)

        # --- Requirement outcome ----------------------------------------------
        if proposed_value is None:
            evidence.status = "rejected_needs_retake"
            evidence.review_note = (
                "No usable reading: OCR failed and manual entry is disabled"
                if not manual_allowed else "No reading provided"
            )
            evidence.save(ignore_permissions=True)
            _record_event(session, "evidence_rejected", payload={
                "kind": kind, "reason": "no_reading", "ocr": ocr_status})
            session.evidence_state = "needs_retake"
            session.save(ignore_permissions=True)
            return create_success_response(
                message="Evidence stored but a reading is required - please retake",
                data={"status": "needs_retake", "evidence": evidence.name},
            )

        if late:
            evidence.status = "late_under_review"
            evidence.save(ignore_permissions=True)
            frappe.db.set_value("NetraNext Trip Odometer Requirement",
                                requirement,
                                {"status": "late_under_review", "late": 1,
                                 "evidence": evidence.name})
            _record_event(session, "evidence_submitted", payload={
                "kind": kind, "late": True, "evidence": evidence.name})
            _refresh_evidence_state(session)
            session.save(ignore_permissions=True)
            if session.journey:
                frappe.db.set_value("NetraNext Journey", session.journey,
                                    "evidence_status", "late_evidence_review")
            return create_success_response(
                message="Late evidence recorded - pending reviewer validation",
                data={"status": "late_under_review", "evidence": evidence.name},
            )

        evidence.status = "validated"
        evidence.save(ignore_permissions=True)
        frappe.db.set_value("NetraNext Trip Odometer Requirement",
                            requirement,
                            {"status": "satisfied", "evidence": evidence.name,
                             "reading_value": flt(proposed_value),
                             "resolved_at": now_datetime()})
        _record_event(session, "evidence_validated", payload={
            "kind": kind, "reading": proposed_value, "evidence": evidence.name})

        _refresh_evidence_state(session)
        session.save(ignore_permissions=True)
        if session.journey:
            journey = frappe.get_doc("NetraNext Journey", session.journey)
            _apply_validated_readings(session, journey)
            journey.evidence_status = session.evidence_state
            if journey.status == "Completed":
                journey.finance_status = _finance_status_for(session)
            journey.save(ignore_permissions=True)
            _release_claim_when_eligible(session, journey)

        return create_success_response(
            message="Odometer evidence validated",
            data={"status": "satisfied", "evidence": evidence.name,
                  "reading_value": flt(proposed_value)},
        )
    except Exception as e:
        return handle_api_exception(e, "ATT_TRIP")


# ---------------------------------------------------------------------------
# Reminder discovery + send-time validation (Service bench crons)
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def get_pending_evidence_reminders():
    """Discovery feed for the central */5 cron (plan sections 6-8).

    Returns reminder items with a stable identity so the central bench can
    dedupe/reschedule:
    - odometer_start / odometer_end: pending requirement, still inside the
      relevance window, fewer than EVIDENCE_REMINDER_MAX sent.
    - attendance_checkout: employee checked in but never checked out;
      hourly reminders starting 1h after shift end (approved decision),
      repeating every hour until checkout (no cap).
    """
    try:
        from netranext_client.netranext.apis.v1.sync import validate_sync_request
        validate_sync_request()

        if not _auto_tracking_enabled():
            return create_success_response(
                message="disabled", data={"reminders": []}
            )

        _, to_naive_local, iso_of = _reminder_tz_helpers()
        now = now_datetime()
        items = []

        requirements = frappe.get_all(
            "NetraNext Trip Odometer Requirement",
            filters={"status": "pending"},
            fields=["session", "kind", "due_at", "reminders_sent",
                    "last_reminder_at", "requirement_key"],
        )
        for req in requirements:
            session = frappe.db.get_value(
                "NetraNext Attendance Trip Session", req.session,
                ["session_id", "user_id", "employee",
                 "movement_confirmed_at", "checkout_time", "status"],
                as_dict=True,
            )
            if not session or not session.user_id:
                continue
            if req.kind == "start":
                anchor = session.movement_confirmed_at
                if not anchor:
                    continue  # no departure yet: photo still optional
                if now > get_datetime(anchor) + timedelta(
                        minutes=REQUIREMENT_RELEVANCE_MIN):
                    continue
            else:
                anchor = session.checkout_time
                if not anchor or session.status != "completed":
                    continue

            base = req.due_at or (
                get_datetime(anchor) + timedelta(minutes=EVIDENCE_GRACE_MIN))
            if req.reminders_sent and req.last_reminder_at:
                next_at = get_datetime(req.last_reminder_at) + timedelta(
                    minutes=EVIDENCE_REMINDER_INTERVAL_MIN)
            else:
                next_at = get_datetime(base)
            if (req.reminders_sent or 0) >= EVIDENCE_REMINDER_MAX:
                continue
            if next_at < now:
                next_at = now

            items.append({
                "reminder_type": "odometer_start" if req.kind == "start"
                else "odometer_end",
                "requirement_key": req.requirement_key,
                "session_id": session.session_id,
                "user_id": session.user_id,
                "employee_id": session.employee,
                "employee_name": frappe.db.get_value(
                    "Employee", session.employee, "employee_name"),
                "send_at_iso": iso_of(to_naive_local(next_at)),
                "kind": req.kind,
            })

        # Checkout reminders: open sessions past shift end + 1h.
        open_sessions = frappe.get_all(
            "NetraNext Attendance Trip Session",
            filters={"status": ["in", ["monitoring", "trip_active"]]},
            fields=["session_id", "user_id", "employee", "shift_ends_at",
                    "reminders_sent_checkout", "last_reminder_at"],
        )
        for session in open_sessions:
            if not session.user_id or not session.shift_ends_at:
                continue
            first_at = get_datetime(session.shift_ends_at) + timedelta(
                minutes=CHECKOUT_REMINDER_DELAY_MIN)
            if now < first_at:
                continue
            if now > first_at + timedelta(hours=CHECKOUT_REMINDER_RELEVANCE_H):
                continue  # stop scheduling after 12h; session stays open
            if session.last_reminder_at:
                next_at = get_datetime(session.last_reminder_at) + timedelta(
                    minutes=CHECKOUT_REMINDER_INTERVAL_MIN)
            else:
                next_at = first_at
            if next_at < now:
                next_at = now
            hour_bucket = int((now - first_at).total_seconds() // 3600)
            items.append({
                "reminder_type": "attendance_checkout",
                "requirement_key": f"{session.session_id}:checkout",
                "window_id": f"{session.session_id}:{hour_bucket}",
                "session_id": session.session_id,
                "user_id": session.user_id,
                "employee_id": session.employee,
                "employee_name": frappe.db.get_value(
                    "Employee", session.employee, "employee_name"),
                "send_at_iso": iso_of(to_naive_local(next_at)),
                "kind": "checkout",
            })

        return create_success_response(
            message="pending evidence reminders",
            data={"reminders": items},
        )
    except Exception as e:
        return handle_api_exception(e, "ATT_TRIP")


@frappe.whitelist(allow_guest=True)
def validate_evidence_reminder(requirement_key=None, reminder_type=None,
                               window_id=None):
    """Send-time re-validation for the central 1-min dispatcher.

    Increments the authoritative reminder counters exactly once per sent
    reminder (the central bench only schedules; this bench counts).
    """
    try:
        from netranext_client.netranext.apis.v1.sync import validate_sync_request
        validate_sync_request()

        now = now_datetime()

        if reminder_type == "attendance_checkout":
            session_id = (requirement_key or "").split(":")[0]
            session_name = frappe.db.get_value(
                "NetraNext Attendance Trip Session",
                {"session_id": session_id}, "name",
            )
            if not session_name:
                return _reminder_invalid("unknown_session")
            session = frappe.get_doc(
                "NetraNext Attendance Trip Session", session_name)
            if session.status not in ("monitoring", "trip_active"):
                return _reminder_invalid("session_closed")
            shift_end = get_datetime(session.shift_ends_at) \
                if session.shift_ends_at else None
            if not shift_end or now < shift_end + timedelta(
                    minutes=CHECKOUT_REMINDER_DELAY_MIN):
                return _reminder_invalid("before_delay_window")
            session.reminders_sent_checkout = (
                session.reminders_sent_checkout or 0) + 1
            session.last_reminder_at = now
            session.save(ignore_permissions=True)
            return create_success_response(
                message="valid", data={"valid": True}
            )

        req = frappe.db.get_value(
            "NetraNext Trip Odometer Requirement",
            {"requirement_key": requirement_key},
            ["name", "session", "kind", "status", "reminders_sent"],
            as_dict=True,
        )
        if not req:
            return _reminder_invalid("unknown_requirement")
        if req.status != "pending":
            return _reminder_invalid(f"requirement_{req.status}")
        if (req.reminders_sent or 0) >= EVIDENCE_REMINDER_MAX:
            return _reminder_invalid("max_reminders_reached")

        session = frappe.db.get_value(
            "NetraNext Attendance Trip Session", req.session,
            ["movement_confirmed_at", "status"], as_dict=True,
        )
        if req.kind == "start" and not session.movement_confirmed_at:
            return _reminder_invalid("no_departure_yet")
        if req.kind == "end" and session.status != "completed":
            return _reminder_invalid("session_not_closed")

        reminder_row = frappe.get_doc("NetraNext Trip Odometer Requirement",
                                      req.name)
        reminder_row.reminders_sent = (reminder_row.reminders_sent or 0) + 1
        reminder_row.last_reminder_at = now
        reminder_row.save(ignore_permissions=True)
        return create_success_response(message="valid", data={"valid": True})
    except Exception as e:
        return handle_api_exception(e, "ATT_TRIP")


def _reminder_invalid(reason):
    return create_success_response(
        message="reminder not valid", data={"valid": False, "reason": reason}
    )


# ---------------------------------------------------------------------------
# Reviewer exception flow (client bench desk users)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def request_evidence_exception(session_id, kind, reason):
    """Employee-facing request: mark a requirement as exception_requested."""
    session_name = frappe.db.get_value(
        "NetraNext Attendance Trip Session", {"session_id": session_id}, "name"
    )
    if not session_name:
        frappe.throw("Unknown session")
    req = frappe.db.get_value(
        "NetraNext Trip Odometer Requirement",
        {"session": session_name, "kind": kind}, "name",
    )
    if not req:
        frappe.throw("No such requirement")
    doc = frappe.get_doc("NetraNext Trip Odometer Requirement", req)
    doc.status = "exception_requested"
    doc.reviewer_note = f"Requested: {reason}"
    doc.save(ignore_permissions=False)
    session = frappe.get_doc("NetraNext Attendance Trip Session", session_name)
    _refresh_evidence_state(session)
    session.save(ignore_permissions=True)
    _record_event(session, "exception_requested", payload={
        "kind": kind, "reason": reason})
    return create_success_response(message="Exception requested",
                                   data={"status": "exception_requested"})


@frappe.whitelist()
def review_evidence_exception(requirement_key, approve, reading_value=None,
                              distance_basis=None, note=None):
    """HR reviewer decision on a late/exception requirement.

    approve=Yes with reading_value validates the reading (accepted_late);
    distance_basis='gps' explicitly allows GPS distance for the claim
    (approved odometer-first decision: GPS only via reviewer exception).
    """
    req = frappe.db.get_value(
        "NetraNext Trip Odometer Requirement",
        {"requirement_key": requirement_key}, "name",
    )
    if not req:
        frappe.throw("Unknown requirement")
    doc = frappe.get_doc("NetraNext Trip Odometer Requirement", req)
    session = frappe.get_doc("NetraNext Attendance Trip Session", doc.session)

    if approve in (1, "1", True, "true", "Yes", "yes"):
        if doc.evidence:
            evidence = frappe.get_doc("NetraNext Trip Odometer Evidence",
                                      doc.evidence)
            evidence.status = "accepted_late"
            evidence.review_note = note or "Approved by reviewer"
            evidence.save(ignore_permissions=True)
        if reading_value is not None:
            doc.reading_value = flt(reading_value)
        doc.status = "satisfied"
        doc.resolved_at = now_datetime()
        doc.resolved_by = frappe.session.user
        if note:
            doc.reviewer_note = note
        doc.save(ignore_permissions=True)
        _record_event(session, "exception_reviewed", payload={
            "kind": doc.kind, "approved": True, "reading": reading_value})
        if session.journey:
            journey = frappe.get_doc("NetraNext Journey", session.journey)
            _apply_validated_readings(session, journey)
            if distance_basis == "gps":
                journey.financial_distance_basis = "gps"
            if journey.status == "Completed":
                journey.finance_status = _finance_status_for(session)
            journey.save(ignore_permissions=True)
            _release_claim_when_eligible(session, journey)
    else:
        doc.status = "pending"
        doc.reviewer_note = note or "Exception rejected - evidence still required"
        doc.save(ignore_permissions=True)
        _record_event(session, "exception_reviewed", payload={
            "kind": doc.kind, "approved": False})

    _refresh_evidence_state(session)
    session.save(ignore_permissions=True)
    return create_success_response(message="Review recorded",
                                   data={"status": doc.status})


def _reminder_tz_helpers():
    """Naive-local + aware-ISO helpers (same conventions as sync.py)."""
    import pytz
    from frappe.utils import get_system_timezone

    system_tz = pytz.timezone(get_system_timezone() or "UTC")

    def to_naive_local(dt):
        if not dt:
            return None
        if dt.tzinfo is not None:
            return dt.astimezone(system_tz).replace(tzinfo=None)
        return dt

    def iso_of(dt_naive_local):
        if not dt_naive_local:
            return None
        if dt_naive_local.tzinfo is not None:
            return dt_naive_local.isoformat()
        return system_tz.localize(dt_naive_local).isoformat()

    return system_tz, to_naive_local, iso_of
