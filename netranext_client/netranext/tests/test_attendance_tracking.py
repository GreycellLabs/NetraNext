"""Unit tests for the attendance-based automatic trip tracking state machine.

Run: <bench>/env/bin/python -m unittest discover \
        -s NetraNext/apps/netranext_client/netranext_client/netranext/tests \
        -t . -p "test_attendance_tracking.py" -v

No bench/database required: frappe is replaced by the in-memory double in
_frape_fake, the movement validator is the real shared module, and the
journey doctype controller (finance gate) is the real file.
"""
import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

HERE = Path(__file__).resolve().parent
MODULE_ROOT = HERE.parent  # .../netranext_client/netranext_client/netranext
sys.path.insert(0, str(HERE))

from _frappe_fake import build_fake, advance_clock, set_clock  # noqa: E402


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class AttendanceTrackingTestBase(unittest.TestCase):
    ENABLED_SETTINGS = {
        "enable_auto_attendance_trip_tracking": 1,
        "enable_odometer_reading": 1,
        "allow_manual_odometer_edit": 1,
        "expense_rate": 0,
        "expense_claim_type": None,
    }

    def setUp(self):
        self.frappe, self.utils, self.store = build_fake(
            settings=dict(self.ENABLED_SETTINGS),
            clock=datetime(2026, 11, 2, 9, 0, 0),
        )
        # Journey finance-gate helpers need a Document base class.
        frappe_model = types.ModuleType("frappe.model")
        frappe_model_document = types.ModuleType("frappe.model.document")
        frappe_model_document.Document = type("Document", (object,), {})
        sys.modules["frappe.model"] = frappe_model
        sys.modules["frappe.model.document"] = frappe_model_document

        logger = types.ModuleType("netranext_client.netranext.utils.logger")
        logger.tenant_bench_logger = MagicMock()
        response = types.ModuleType(
            "netranext_client.netranext.utils.response_formatter")
        response.create_success_response = (
            lambda message, data=None, **kw: dict(status="success",
                                                  message=message, data=data))
        response.create_error_response = (
            lambda message, data=None, **kw: dict(status="error",
                                                  message=message, data=data))
        error_handler = types.ModuleType(
            "netranext_client.netranext.utils.error_handler")
        error_handler.handle_api_exception = (
            lambda e, context="": dict(status="error", message=str(e)))
        error_handler.ValidationException = type("ValidationException",
                                                 (Exception,), {})
        error_handler.AuthenticationException = type(
            "AuthenticationException", (Exception,), {})
        validators = types.ModuleType(
            "netranext_client.netranext.utils.validators")
        validators.validate_required_fields = lambda *a, **k: None
        validators.validate_employee_exists = lambda *a, **k: None
        sync_stub = types.ModuleType("netranext_client.netranext.apis.v1.sync")
        sync_stub.validate_sync_request = lambda: True
        sync_stub.create_success_response = response.create_success_response

        movement = load_module(
            "netranext_client.netranext.utils.movement_validation",
            MODULE_ROOT / "utils" / "movement_validation.py")
        self.journey_module = load_module(
            "netranext_client.netranext.doctype."
            "netranext_journey.netranext_journey",
            MODULE_ROOT / "doctype" / "netranext_journey" /
            "netranext_journey.py")

        for parent in ("netranext_client",
                       "netranext_client.netranext",
                       "netranext_client.netranext.utils",
                       "netranext_client.netranext.apis",
                       "netranext_client.netranext.apis.v1",
                       "netranext_client.netranext.doctype",
                       "netranext_client.netranext.doctype."
                       "netranext_journey"):
            sys.modules.setdefault(parent, types.ModuleType(parent))

        file_manager = types.ModuleType("frappe.utils.file_manager")
        file_manager.save_file = MagicMock(
            return_value=types.SimpleNamespace(file_url="/private/files/x.jpg"))

        self.patcher = patch.dict(sys.modules, {
            "frappe": self.frappe,
            "frappe.utils": self.utils,
            "frappe.utils.file_manager": file_manager,
            "netranext_client.netranext.utils.logger": logger,
            "netranext_client.netranext.utils.response_formatter": response,
            "netranext_client.netranext.utils.error_handler": error_handler,
            "netranext_client.netranext.utils.validators": validators,
            "netranext_client.netranext.utils.movement_validation": movement,
            "netranext_client.netranext.apis.v1.sync": sync_stub,
            "netranext_client.netranext.doctype."
            "netranext_journey.netranext_journey": self.journey_module,
        })
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(sys.modules.pop, "netranext_client.netranext.apis.v1."
                                           "attendance_tracking", None)

        self.api = load_module(
            "netranext_client.netranext.apis.v1.attendance_tracking",
            MODULE_ROOT / "apis" / "v1" / "attendance_tracking.py")

        # Realistic employee + movement fixtures.
        self.employee = "EMP-001"
        self.t0 = int(datetime(2026, 11, 2, 9, 0, 0).timestamp() * 1000)
        self.anchor = {"latitude": 12.9716, "longitude": 77.5946,
                       "accuracy": 10, "timestamp": self.t0}

    # -- helpers ---------------------------------------------------------
    def checked_in(self, session_id="ats-1", accuracy=10):
        return self.api.handle_checkin_stored({
            "employee_id": self.employee,
            "user_id": "user1@example.com",
            "time": "2026-11-02 09:00:00",
            "log_type": "IN",
            "latitude": self.anchor["latitude"],
            "longitude": self.anchor["longitude"],
            "tracking_accuracy": accuracy,
            "tracking_session_id": session_id,
        }, "CHKIN-001")

    def walking_fixes(self, count=4, start_s=8, step_s=8, base_m=150):
        from math import cos, radians
        m_per_deg = 111194.9269
        fixes = []
        for i in range(count):
            meters = base_m + i * 20
            fixes.append({
                "latitude": self.anchor["latitude"] + meters / m_per_deg,
                "longitude": self.anchor["longitude"],
                "accuracy": 8,
                "timestamp": self.t0 + (start_s + i * step_s) * 1000,
            })
        assert cos(radians(0))  # silence linters; keep formula obvious
        return fixes

    def movement_event(self, session_id="ats-1", event_id="evt-1"):
        return {
            "event_id": event_id,
            "session_id": session_id,
            "employee_id": self.employee,
            "event_type": "movement_confirmed",
            "occurred_at_ms": self.t0 + 32_000,
            "anchor_timestamp_ms": self.t0,
            "observed_start_at_ms": self.t0 + 24_000,
            "fixes": self.walking_fixes(),
        }

    def evidence(self, kind="start", capture_offset_s=-120, ocr_value=50000.0,
                 ocr_status="detected", session_id="ats-1", evidence_id="evd-1"):
        base = datetime(2026, 11, 2, 9, 0, 0)
        if kind == "start":
            capture = base + timedelta(seconds=capture_offset_s)
        else:
            capture = base + timedelta(hours=2, minutes=30,
                                       seconds=capture_offset_s)
        return {
            "evidence_id": evidence_id,
            "session_id": session_id,
            "kind": kind,
            "photo_base64": "aGVsbG8=",
            "photo_hash": None,  # hash check only runs when provided
            "client_captured_at_ms": int(capture.timestamp() * 1000),
            "ocr": {"status": ocr_status, "value": ocr_value,
                    "raw_text": "50000", "request_id": "req-1"},
            "source": "detected" if ocr_status == "detected" else "manual",
        }


class MovementValidatorFixtureTests(AttendanceTrackingTestBase):
    def test_shared_fixtures(self):
        fixture_path = HERE / "fixtures" / "movement_validation_cases.json"
        doc = json.loads(fixture_path.read_text())
        results = []
        for case in doc["cases"]:
            verdict = self.api.evaluate_movement(
                case["anchor"], case["fixes"], now_ms=case.get("now_ms"))
            results.append((case["name"],
                            verdict["status"] == case["expect_status"]))
        failures = [name for name, ok in results if not ok]
        self.assertEqual(failures, [], f"fixture failures: {failures}")


class SessionLifecycleTests(AttendanceTrackingTestBase):
    def test_disabled_setting_creates_nothing(self):
        self.store.settings["enable_auto_attendance_trip_tracking"] = 0
        payload = self.api.handle_checkin_stored({
            "employee_id": self.employee, "time": "2026-11-02 09:00:00",
            "log_type": "IN", "latitude": 1.0, "longitude": 1.0,
        }, "CHKIN-001")
        self.assertIsNone(payload)
        self.assertEqual(self.store.get("NetraNext Attendance Trip Session"),
                         [])
        self.assertEqual(self.store.get("NetraNext Trip Odometer Requirement"),
                         [])

    def test_checkin_opens_session_and_start_requirement(self):
        payload = self.checked_in()
        self.assertEqual(payload["status"], "monitoring")
        self.assertEqual(payload["monitor_state"], "awaiting_movement")
        self.assertTrue(payload["reserved_journey_id"].startswith("auto-"))
        self.assertTrue(payload["odometer_required"])
        self.assertEqual(payload["evidence_state"], "pending_predeparture")
        self.assertEqual(len(payload["requirements"]), 1)
        self.assertEqual(payload["requirements"][0]["kind"], "start")

    def test_checkin_without_odometer_setting(self):
        self.store.settings["enable_odometer_reading"] = 0
        payload = self.checked_in()
        self.assertFalse(payload["odometer_required"])
        self.assertEqual(payload["evidence_state"], "not_required")
        self.assertEqual(payload["requirements"], [])

    def test_duplicate_checkin_replays_same_session(self):
        first = self.checked_in()
        second = self.checked_in()
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(len(self.store.get("NetraNext Attendance Trip "
                                            "Session")), 1)

    def test_second_checkin_cancels_stale_session(self):
        first = self.checked_in(session_id="ats-1")
        second = self.checked_in(session_id="ats-2")
        self.assertEqual(first["session_id"], "ats-1")
        self.assertEqual(second["session_id"], "ats-2")
        statuses = {row["session_id"]: row["status"] for row in
                    self.store.get("NetraNext Attendance Trip Session")}
        self.assertEqual(statuses["ats-1"], "cancelled")
        self.assertEqual(statuses["ats-2"], "monitoring")


class MovementConfirmationTests(AttendanceTrackingTestBase):
    def test_confirmed_movement_starts_trip_with_reserved_id(self):
        session = self.checked_in()
        outcome = self.api._apply_event(self.movement_event())
        self.assertTrue(outcome.get("trip_started"))
        journeys = self.store.get("NetraNext Journey")
        self.assertEqual(len(journeys), 1)
        journey = journeys[0]
        self.assertEqual(journey["flutter_journey_id"],
                         session["reserved_journey_id"])
        self.assertEqual(journey["tracking_source"], "attendance_auto")
        self.assertEqual(journey["attendance_session"],
                         session["session_name"])
        self.assertEqual(journey["status"], "In Progress")
        self.assertEqual(journey["finance_status"], "blocked_pending_evidence")
        updated = next(r for r in self.store.get(
            "NetraNext Attendance Trip Session")
            if r["session_id"] == "ats-1")
        self.assertEqual(updated["status"], "trip_active")
        self.assertEqual(updated["journey"], journey["name"])

    def test_replayed_event_id_is_idempotent(self):
        self.checked_in()
        first = self.api._apply_event(self.movement_event(event_id="evt-1"))
        second = self.api._apply_event(self.movement_event(event_id="evt-1"))
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(len(self.store.get("NetraNext Journey")), 1)
        self.assertEqual(first["journey"], second["journey"])

    def test_unvalidated_movement_rejected_by_server(self):
        self.checked_in()
        event = self.movement_event()
        # Replace fixes with GPS jitter that never left the accuracy budget.
        event["fixes"] = [{
            "latitude": self.anchor["latitude"] + 0.00003,
            "longitude": self.anchor["longitude"],
            "accuracy": 8,
            "timestamp": self.t0 + (8 + i * 8) * 1000,
        } for i in range(4)]
        outcome = self.api._apply_event(event)
        self.assertEqual(outcome.get("rejected"),
                         "movement_not_confirmed_by_server")
        self.assertEqual(self.store.get("NetraNext Journey"), [])

    def test_manual_trip_active_suppresses_auto_start(self):
        self.checked_in()
        self.store.get("NetraNext Journey").append({
            "doctype": "NetraNext Journey", "name": "JOURNEY-MANUAL",
            "employee": self.employee, "status": "In Progress",
            "tracking_source": "manual",
        })
        outcome = self.api._apply_event(self.movement_event())
        self.assertTrue(outcome.get("ownership_conflict"))
        self.assertEqual(len(self.store.get("NetraNext Journey")), 1)
        session = next(r for r in self.store.get(
            "NetraNext Attendance Trip Session"))
        self.assertEqual(session["monitor_state"], "suspended_conflict")
        self.assertTrue(session["ownership_conflict"])

    def test_submit_events_disabled_setting_short_circuits(self):
        self.store.settings["enable_auto_attendance_trip_tracking"] = 0
        response = self.api.submit_events([self.movement_event()])
        self.assertFalse(response["data"]["enabled"])
        self.assertEqual(self.store.get("NetraNext Journey"), [])


class CheckoutTests(AttendanceTrackingTestBase):
    def test_checkout_ends_trip_and_blocks_finance_until_evidence(self):
        self.checked_in()
        self.api._apply_event(self.movement_event())
        advance_clock(hours=2)
        payload = self.api.handle_checkout_stored({
            "employee_id": self.employee,
            "user_id": "user1@example.com",
            "time": "2026-11-02 11:00:00",
            "log_type": "OUT",
        }, "CHKOUT-001")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["evidence_state"], "pending_end")
        journey = next(r for r in self.store.get("NetraNext Journey"))
        self.assertEqual(journey["status"], "Completed")
        self.assertEqual(journey["finance_status"], "blocked_pending_evidence")
        kinds = sorted(r["kind"] for r in self.store.get(
            "NetraNext Trip Odometer Requirement"))
        self.assertEqual(kinds, ["end", "start"])

    def test_checkout_without_movement_creates_no_trip(self):
        self.checked_in()
        payload = self.api.handle_checkout_stored({
            "employee_id": self.employee,
            "time": "2026-11-02 11:00:00", "log_type": "OUT",
        }, "CHKOUT-001")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(self.store.get("NetraNext Journey"), [])
        start_req = next(r for r in self.store.get(
            "NetraNext Trip Odometer Requirement"))
        self.assertEqual(start_req["status"], "not_required")
        self.assertEqual(payload["evidence_state"], "not_required")


class EvidenceTests(AttendanceTrackingTestBase):
    def test_on_time_start_evidence_satisfies_requirement(self):
        self.checked_in()
        self.api._apply_event(self.movement_event())
        response = self.api.store_odometer_evidence(self.evidence())
        data = response["data"]
        self.assertEqual(data["status"], "satisfied")
        journey = next(r for r in self.store.get("NetraNext Journey"))
        self.assertEqual(journey["start_odometer"], 50000.0)
        requirement = next(r for r in self.store.get(
            "NetraNext Trip Odometer Requirement"))
        self.assertEqual(requirement["status"], "satisfied")

    def test_pre_departure_evidence_before_any_movement(self):
        self.checked_in()
        response = self.api.store_odometer_evidence(
            self.evidence(capture_offset_s=600))
        self.assertEqual(response["data"]["status"], "satisfied")

    def test_late_start_evidence_never_auto_populates_journey(self):
        self.checked_in()
        self.api._apply_event(self.movement_event())
        advance_clock(minutes=30)
        response = self.api.store_odometer_evidence(
            self.evidence(capture_offset_s=1500))  # 25 min AFTER departure
        self.assertEqual(response["data"]["status"], "late_under_review")
        journey = next(r for r in self.store.get("NetraNext Journey"))
        self.assertIsNone(journey.get("start_odometer"))
        requirement = next(r for r in self.store.get(
            "NetraNext Trip Odometer Requirement"))
        self.assertEqual(requirement["status"], "late_under_review")
        self.assertEqual(journey["evidence_status"], "late_evidence_review")

    def test_ocr_failure_with_manual_disabled_needs_retake(self):
        self.store.settings["allow_manual_odometer_edit"] = 0
        self.checked_in()
        response = self.api.store_odometer_evidence(
            self.evidence(ocr_status="no_text", ocr_value=None))
        self.assertEqual(response["data"]["status"], "needs_retake")
        requirement = next(r for r in self.store.get(
            "NetraNext Trip Odometer Requirement"))
        self.assertEqual(requirement["status"], "pending")

    def test_duplicate_evidence_id_is_idempotent(self):
        self.checked_in()
        first = self.api.store_odometer_evidence(self.evidence())
        second = self.api.store_odometer_evidence(self.evidence())
        self.assertEqual(second["data"]["status"], "duplicate")
        self.assertEqual(len(self.store.get("NetraNext Trip Odometer "
                                            "Evidence")), 1)

    def test_full_cycle_releases_claim_when_evidence_complete(self):
        self.store.settings["expense_rate"] = 5.0
        self.store.settings["expense_claim_type"] = "Travel"
        created = []
        original = self.journey_module.create_expense_claim_for_journey
        # Trace claim release without executing the full claim upsert. The
        # journey doc here is the in-memory fake, so the seam is the
        # module-level release function the evidence path calls.
        def spy(journey):
            created.append((journey.name, journey.finance_status,
                            journey.tracking_source))
        self.journey_module.create_expense_claim_for_journey = spy
        try:
            self.checked_in()
            self.api._apply_event(self.movement_event())
            self.assertEqual(created, [])  # blocked while evidence pending

            start_response = self.api.store_odometer_evidence(self.evidence())
            self.assertEqual(start_response["data"]["status"], "satisfied")
            self.assertEqual(created, [])  # trip still In Progress

            advance_clock(hours=2)
            self.api.handle_checkout_stored({
                "employee_id": self.employee,
                "time": "2026-11-02 11:00:00", "log_type": "OUT",
            }, "CHKOUT-001")
            self.assertEqual(created, [])  # end evidence still pending

            end_evidence = self.evidence(kind="end", capture_offset_s=300,
                                         ocr_value=50120.0,
                                         evidence_id="evd-2")
            response = self.api.store_odometer_evidence(end_evidence)
            self.assertEqual(response["data"]["status"], "satisfied")
            self.assertEqual(len(created), 1)  # released now
            self.assertEqual(created[0][2], "attendance_auto")
            journey = next(r for r in self.store.get("NetraNext Journey"))
            self.assertEqual(journey["end_odometer"], 50120.0)
            self.assertEqual(journey["start_odometer"], 50000.0)
            self.assertEqual(journey["calculated_odometer_distance"], 120.0)
            self.assertEqual(journey["financial_distance_basis"], "odometer")
            self.assertEqual(journey["finance_status"], "claim_created")
        finally:
            self.journey_module.create_expense_claim_for_journey = original


class FinanceGateTests(AttendanceTrackingTestBase):
    def test_manual_journeys_bypass_gate(self):
        self.assertTrue(self.journey_module._auto_trip_finance_ready(
            types.SimpleNamespace(tracking_source="manual",
                                  finance_status=None)))
        self.assertTrue(self.journey_module._auto_trip_finance_ready(
            types.SimpleNamespace(tracking_source=None)))

    def test_auto_journeys_need_eligible_status(self):
        gate = self.journey_module._auto_trip_finance_ready
        self.assertFalse(gate(types.SimpleNamespace(
            tracking_source="attendance_auto",
            finance_status="blocked_pending_evidence")))
        self.assertTrue(gate(types.SimpleNamespace(
            tracking_source="attendance_auto", finance_status="eligible")))
        self.assertTrue(gate(types.SimpleNamespace(
            tracking_source="attendance_auto",
            finance_status="claim_created")))


class ReminderTests(AttendanceTrackingTestBase):
    def test_no_start_reminders_before_departure(self):
        self.checked_in()
        advance_clock(minutes=30)
        response = self.api.get_pending_evidence_reminders()
        kinds = [item["reminder_type"] for item in response["data"]["reminders"]]
        self.assertNotIn("odometer_start", kinds)

    def test_start_reminder_after_departure(self):
        self.checked_in()
        self.api._apply_event(self.movement_event())
        advance_clock(minutes=20)  # past the 15-minute grace
        response = self.api.get_pending_evidence_reminders()
        starts = [item for item in response["data"]["reminders"]
                  if item["reminder_type"] == "odometer_start"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["requirement_key"], "ats-1:start")
        self.assertEqual(starts[0]["user_id"], "user1@example.com")

    def test_checkout_reminder_starts_one_hour_after_shift_end(self):
        self.checked_in()
        # shift_ends_at = 9h + fallback 9h = 18:00; first reminder at 19:00.
        set_clock(datetime(2026, 11, 2, 19, 5, 0))
        response = self.api.get_pending_evidence_reminders()
        checkouts = [item for item in response["data"]["reminders"]
                     if item["reminder_type"] == "attendance_checkout"]
        self.assertEqual(len(checkouts), 1)
        self.assertEqual(checkouts[0]["requirement_key"], "ats-1:checkout")

    def test_no_checkout_reminder_within_first_hour(self):
        self.checked_in()
        set_clock(datetime(2026, 11, 2, 18, 30, 0))  # shift end 18:00
        response = self.api.get_pending_evidence_reminders()
        kinds = [item["reminder_type"] for item in response["data"]["reminders"]]
        self.assertNotIn("attendance_checkout", kinds)

    def test_validate_reminder_increments_and_caps(self):
        self.checked_in()
        self.api._apply_event(self.movement_event())
        for expected_count in (1, 2):
            response = self.api.validate_evidence_reminder(
                requirement_key="ats-1:start",
                reminder_type="odometer_start")
            self.assertTrue(response["data"]["valid"])
        response = self.api.validate_evidence_reminder(
            requirement_key="ats-1:start", reminder_type="odometer_start")
        self.assertFalse(response["data"]["valid"])
        self.assertEqual(response["data"]["reason"], "max_reminders_reached")
        requirement = next(r for r in self.store.get(
            "NetraNext Trip Odometer Requirement"))
        self.assertEqual(requirement["reminders_sent"], 2)

    def test_satisfied_requirement_stops_reminders(self):
        self.checked_in()
        self.api._apply_event(self.movement_event())
        self.api.store_odometer_evidence(self.evidence())
        advance_clock(minutes=20)
        response = self.api.get_pending_evidence_reminders()
        kinds = [item["reminder_type"] for item in response["data"]["reminders"]]
        self.assertNotIn("odometer_start", kinds)
        response = self.api.validate_evidence_reminder(
            requirement_key="ats-1:start", reminder_type="odometer_start")
        self.assertFalse(response["data"]["valid"])

    def test_checkout_validation_counts_hourly(self):
        self.checked_in()
        set_clock(datetime(2026, 11, 2, 19, 5, 0))
        first = self.api.validate_evidence_reminder(
            requirement_key="ats-1:checkout",
            reminder_type="attendance_checkout")
        self.assertTrue(first["data"]["valid"])
        session = next(r for r in self.store.get(
            "NetraNext Attendance Trip Session"))
        self.assertEqual(session["reminders_sent_checkout"], 1)


if __name__ == "__main__":
    unittest.main()
