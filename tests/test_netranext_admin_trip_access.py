"""NetraNext Admin trip access regressions (no bench, no database).

Reproduces "Not permitted - No permission for NetraNext Journey <name>" on the
Trip Details desk page for a NetraNext Admin who is also an HRMS employee, and
checks the fix: Admin reads every employee's trips, EMP users only their own,
users with neither role nothing.

`frappe.has_permission` is replaced by a small model of Frappe's evaluation
(role rows -> doc has_permission hook -> User Permissions on link fields),
fed from the real NetraNext Journey JSON, hooks.py, Custom DocPerm rows and
Property Setters, so the real policy, page, dashboard and patch code run
against it.

Run: python3 -m unittest discover -s tests -p test_netranext_admin_trip_access.py
"""
import importlib.util
import json
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1] / "netranext_client"
POLICY = "netranext_client.netranext.utils.trip_permissions"
ROLE_PATCH = "netranext_client.netranext.patches.create_netranext_admin_role"
JOURNEY = "NetraNext Journey"
JOURNEY_JSON = ROOT / "netranext/doctype/netranext_journey/netranext_journey.json"

ADMIN, ALICE, BOB, NOBODY = "admin@example.com", "alice@example.com", "bob@example.com", "nobody@example.com"


class Denied(Exception):
    http_status_code = 403


class Row(dict):
    def __getattr__(self, key):
        return self.get(key)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registered_hook(hook_name, doctype):
    """Dotted path registered for `doctype` in hooks.py's `hook_name` dict."""
    text = (ROOT / "hooks.py").read_text()
    block = re.search(r"^" + hook_name + r" = \{(.*?)^\}", text, re.S | re.M).group(1)
    match = re.search(r'"' + re.escape(doctype) + r'":\s*"([^"]+)"', block)
    return match.group(1) if match else None


class FrappePermissionModel:
    """Frappe v15 permission evaluation reduced to what NetraNext Journey uses."""

    def __init__(self, test):
        self.test = test
        meta = json.loads(JOURNEY_JSON.read_text())
        self.json_rows = meta["permissions"]
        self.link_fields = [f for f in meta["fields"] if f.get("fieldtype") == "Link"]
        self.custom_docperms = {}      # doctype -> [rows]; replaces JSON rows when present
        self.property_setters = []     # dicts: doc_type, field_name, property, value
        self.user_permissions = {}     # user -> {allow doctype: [values]}

    def rows(self, doctype):
        return self.custom_docperms.get(doctype) or self.json_rows

    def role_read(self, user, ptype, doc=None):
        roles = set(self.test.roles.get(user, []))
        rows = [r for r in self.rows(JOURNEY)
                if not r.get("permlevel") and r["role"] in roles and r.get(ptype)]
        if not rows:
            return False
        if doc is None:
            return True
        return any(not r.get("if_owner") or doc.get("owner") == user for r in rows)

    def ignores_user_permissions(self, field):
        for ps in self.property_setters:
            if (ps["doc_type"], ps["field_name"], ps["property"]) == (JOURNEY, field["fieldname"],
                                                                     "ignore_user_permissions"):
                return bool(int(ps["value"]))
        return bool(field.get("ignore_user_permissions"))

    def user_permission_ok(self, user, doc):
        allowed = self.user_permissions.get(user, {})
        for field in self.link_fields:
            value = doc.get(field["fieldname"])
            if self.ignores_user_permissions(field) or not value:
                continue
            if allowed.get(field["options"]) and value not in allowed[field["options"]]:
                return False
        return True

    def doc_read(self, user, doc, ptype="read"):
        hook = registered_hook("has_permission", JOURNEY)
        assert hook == POLICY + ".has_permission", hook
        # Frappe v16 (production): any falsy hook result - None included -
        # denies (`if not controller_permission`). v15 only denied on False.
        if not self.test.policy.has_permission(doc, user=user, ptype=ptype):
            return False
        return self.role_read(user, ptype, doc) and self.user_permission_ok(user, doc)

    def has_permission(self, doctype=None, ptype="read", doc=None, user=None, throw=False, **kwargs):
        user = user or self.test.frappe.session.user
        if user == "Administrator":
            return True
        out = self.role_read(user, ptype) if doc is None else self.doc_read(user, doc, ptype)
        if throw and not out:
            raise Denied("No permission for " + doctype + (" " + doc.name if doc is not None else ""))
        return out

    def get_list(self, doctype, filters=None, or_filters=None, **kwargs):
        """DatabaseQuery: role read + permission_query_conditions + User Permissions."""
        assert doctype == JOURNEY and not kwargs.get("ignore_permissions")
        user = self.test.frappe.session.user
        if not self.role_read(user, "read"):
            raise Denied("No permission for " + doctype)
        own_only = bool(self.test.policy.get_permission_query_conditions(user))
        own = set(self.test.employees_of(user))
        result = []
        for trip in self.test.trips.values():
            if own_only and trip.employee not in own:
                continue
            if not self.user_permission_ok(user, trip):
                continue
            if all(self.match(trip, f) for f in filters or []):
                result.append(trip)
        return result

    @staticmethod
    def match(trip, condition):
        field, op, value = condition[0], condition[1], condition[2]
        if op == "=":
            return trip.get(field) == value
        if op == "in":
            return trip.get(field) in value
        if op == "like":
            return str(value).strip("%") in str(trip.get(field) or "")
        return True  # date/status narrowing is irrelevant to scope


class NetraNextAdminTripAccessTests(unittest.TestCase):
    def setUp(self):
        self.frappe = MagicMock()
        self.frappe.whitelist.side_effect = lambda **kw: lambda fn: fn
        self.frappe._ = lambda text: text
        self.frappe.PermissionError = Denied
        self.frappe.throw.side_effect = lambda message, exc=Denied: (_ for _ in ()).throw(exc(message))
        self.roles = {
            ADMIN: ["NetraNext Admin", "Employee"],
            ALICE: ["Employee"],
            BOB: ["Employee"],
            NOBODY: [],
        }
        self.employees = {ADMIN: ["EMP-ADM"], ALICE: ["EMP-A"], BOB: ["EMP-B"]}
        gps = json.dumps([{"latitude": 23.0, "longitude": 72.5, "timestamp": "2026-11-17T09:00:00Z"},
                          {"latitude": 23.1, "longitude": 72.6, "timestamp": "2026-11-17T09:30:00Z"}])
        base = dict(status="Completed", distance_km=3.2, start_time=None, end_time=None, raw_gps_data=gps,
                    metadata=None, owner="integration@example.com", attendance_checkin=None,
                    start_odometer=1200, end_odometer=1203, start_odometer_photo="/private/files/s.jpg",
                    end_odometer_photo="/private/files/e.jpg", start_location="A", end_location="B")
        self.trips = {
            "TRIP-ADM": Row(base, name="TRIP-ADM", employee="EMP-ADM"),
            "TRIP-A": Row(base, name="TRIP-A", employee="EMP-A"),
            "TRIP-B": Row(base, name="TRIP-B", employee="EMP-B"),
            "TRIP-ATT": Row(base, name="TRIP-ATT", employee="EMP-B", attendance_checkin="CHK-0001",
                            reason="Attendance-Based Automatic Start",
                            metadata=json.dumps({"attendance": {"checkin_id": "CHK-0001"},
                                                 "battery_level": 64, "device_model": "Pixel 8"})),
            "TRIP-SCH": Row(base, name="TRIP-SCH", employee="EMP-B",
                            metadata=json.dumps({"tracking_source": "scheduled"})),
        }
        self.model = FrappePermissionModel(self)
        # HRMS creates this for every user linked to an Employee record.
        self.model.user_permissions = {u: {"Employee": list(e)} for u, e in self.employees.items()}
        self.roles_on_site = {"NetraNext Admin", "Employee", "System Manager"}

        self.frappe.get_roles.side_effect = lambda user: self.roles.get(user, [])
        self.frappe.has_permission.side_effect = self.model.has_permission
        self.frappe.get_list.side_effect = self.model.get_list
        self.frappe.db.escape.side_effect = lambda text: "'" + text.replace("'", "''") + "'"
        self.frappe.db.exists.side_effect = self.exists
        self.frappe.db.get_value.side_effect = self.get_value
        self.frappe.get_value.return_value = None
        self.frappe.get_all.side_effect = self.get_all
        self.frappe.db.sql.return_value = []
        self.frappe.db.count.return_value = 0
        self.frappe.db.get_single_value.return_value = 2
        self.frappe.get_doc.side_effect = self.get_doc
        self.frappe.db.delete.side_effect = self.db_delete

        query_module = types.ModuleType("frappe.model.db_query")
        query_module.DatabaseQuery = MagicMock()
        permissions_module = types.ModuleType("frappe.permissions")
        permissions_module.add_permission = self.add_permission
        permissions_module.update_permission_property = self.update_permission_property
        modules = patch.dict(sys.modules, {"frappe": self.frappe, "frappe.model.db_query": query_module,
                                           "frappe.permissions": permissions_module})
        modules.start()
        self.addCleanup(modules.stop)
        self.policy = load("admin_trip_policy_test", ROOT / "netranext/utils/trip_permissions.py")
        role_patch = load("admin_role_patch_test", ROOT / "netranext/patches/create_netranext_admin_role.py")
        imports = patch.dict(sys.modules, {POLICY: self.policy, ROLE_PATCH: role_patch})
        imports.start()
        self.addCleanup(imports.stop)
        self.page = load("admin_trip_page_test",
                         ROOT / "netranext/page/netranext_trip_details/netranext_trip_details.py")
        self.dashboard = load("admin_trip_dashboard_test", ROOT / "netranext/apis/v1/dashboard.py")
        self.access_patch = load("admin_access_patch_test",
                                 ROOT / "netranext/patches/ensure_netranext_admin_record_access.py")

    # ---- DB stubs -------------------------------------------------------
    def employees_of(self, user):
        return self.employees.get(user, [])

    def exists(self, doctype, filters=None):
        if doctype == "Employee" and isinstance(filters, dict):
            return filters["name"] in self.employees_of(filters.get("user_id"))
        if doctype == JOURNEY:
            return filters in self.trips
        if doctype == "Custom DocPerm":
            return bool(self.model.custom_docperms.get(filters["parent"]))
        if doctype == "Role":
            return filters in self.roles_on_site
        return True

    def get_value(self, doctype, filters=None, fields=None, **kwargs):
        if doctype == "User":
            return 1 if filters in self.roles else None
        if doctype == JOURNEY and isinstance(filters, dict):
            return None
        if doctype == "DocPerm":
            for row in self.model.json_rows:
                if row["role"] == filters["role"]:
                    return Row({f: row.get(f, 0) for f in fields})
        return None

    def get_all(self, doctype, filters=None, **kwargs):
        if doctype == "Employee" and kwargs.get("pluck") == "name" and isinstance(filters, dict):
            return self.employees_of(filters.get("user_id"))
        return []

    def get_doc(self, doctype, name=None):
        if doctype == JOURNEY:
            return self.trips[name]
        if isinstance(doctype, dict):
            doc = MagicMock()
            doc.insert.side_effect = lambda: self.roles_on_site.add(doctype["role_name"])
            return doc
        raise KeyError(name)

    def db_delete(self, doctype, filters):
        if doctype == "Property Setter":
            self.model.property_setters = [
                ps for ps in self.model.property_setters
                if not all(ps[k] == v for k, v in filters.items())]

    def add_permission(self, doctype, role, permlevel=0, ptype="read"):
        rows = self.model.custom_docperms.setdefault(doctype, [dict(r) for r in self.model.json_rows])
        if not any(r["role"] == role and not r.get("permlevel") and not r.get("if_owner") for r in rows):
            rows.append({"role": role, "permlevel": permlevel, ptype: 1})

    def update_permission_property(self, doctype, role, permlevel, ptype, value=None, **kwargs):
        for row in self.model.custom_docperms[doctype]:
            if row["role"] == role and row.get("permlevel", 0) == permlevel and not row.get("if_owner"):
                row[ptype] = value

    # ---- helpers ----------------------------------------------------------
    def as_user(self, user):
        self.frappe.session.user = user

    def open_trip(self, user, trip_id):
        self.as_user(user)
        return self.page.get_trip_telemetry_details(trip_id)

    def history_trip_ids(self, user, **kwargs):
        self.as_user(user)
        result = self.dashboard.get_dashboard_data(ignore_dates=1, **kwargs)
        self.assertEqual(result["status"], "success", result)
        return {j["name"] for j in result["data"]["journeys"]}

    def summary_trip_ids(self, user, **kwargs):
        self.as_user(user)
        return {row["name"] for row in self.page.get_all_trips_summary(**kwargs)}

    def simulate_drifted_site(self):
        """Permissions customised in Role Permission Manager before NetraNext
        Admin existed, and `employee` re-exposed to User Permissions via
        Customize Form - the JSON fix never reaches the effective meta."""
        self.model.custom_docperms[JOURNEY] = [dict(r) for r in self.model.json_rows
                                               if r["role"] != "NetraNext Admin"]
        self.model.property_setters.append(dict(doc_type=JOURNEY, field_name="employee",
                                                property="ignore_user_permissions", value="0"))

    # ---- required cases -----------------------------------------------------
    def test_admin_opens_own_trip(self):
        self.assertEqual(self.open_trip(ADMIN, "TRIP-ADM")["employee_id"], "EMP-ADM")

    def test_admin_opens_another_employees_trip(self):
        detail = self.open_trip(ADMIN, "TRIP-B")
        self.assertEqual(detail["employee_id"], "EMP-B")

    def test_admin_trip_details_include_timeline_route_telemetry_and_odometer(self):
        detail = self.open_trip(ADMIN, "TRIP-ATT")
        self.assertEqual(len(detail["raw_gps_data"]), 2)
        self.assertTrue(detail["timeline_events"])
        self.assertIn("telemetry", detail)
        self.assertEqual((detail["start_odometer"], detail["end_odometer"]), (1200, 1203))
        self.assertEqual(detail["start_odometer_photo"], "/private/files/s.jpg")

    def test_admin_opens_attendance_based_and_scheduled_trips(self):
        for trip_id in ("TRIP-ATT", "TRIP-SCH"):
            self.assertEqual(self.open_trip(ADMIN, trip_id)["trip_id"], trip_id)
        # Same standard check odometer photo downloads and /app form use.
        self.assertTrue(self.model.has_permission(JOURNEY, "read", doc=self.trips["TRIP-ATT"], user=ADMIN))

    def test_admin_trip_history_and_trip_list_show_all_trips(self):
        # Trip Details list, and Trip History / Live Tracking (dashboard API).
        self.assertEqual(self.summary_trip_ids(ADMIN), set(self.trips))
        self.assertEqual(self.history_trip_ids(ADMIN), set(self.trips))
        self.assertEqual(self.history_trip_ids(ADMIN, journey_employee="EMP-B"), {"TRIP-B", "TRIP-ATT", "TRIP-SCH"})
        self.assertEqual(self.history_trip_ids(ALICE), {"TRIP-A"})

    def test_emp_opens_own_trip(self):
        self.assertEqual(self.open_trip(ALICE, "TRIP-A")["employee_id"], "EMP-A")

    def test_emp_cannot_open_another_employees_trip(self):
        for trip_id in ("TRIP-B", "TRIP-ATT", "TRIP-ADM"):
            with self.assertRaises(Denied):
                self.open_trip(ALICE, trip_id)

    def test_emp_direct_api_calls_for_another_employees_trip_are_denied(self):
        # Standard REST /api/resource/NetraNext Journey/TRIP-B document read.
        self.assertFalse(self.model.has_permission(JOURNEY, "read", doc=self.trips["TRIP-B"], user=ALICE))
        # Whitelisted page APIs with spoofed employee filters.
        self.assertEqual(self.summary_trip_ids(ALICE, employee="EMP-B"), set())
        self.assertEqual(self.summary_trip_ids(ALICE), {"TRIP-A"})
        self.as_user(ALICE)
        self.assertEqual(self.history_trip_ids(ALICE, journey_employee="EMP-B", user_id=BOB), set())

    def test_user_without_admin_or_employee_role_is_denied(self):
        self.employees[NOBODY] = ["EMP-N"]
        with self.assertRaises(Denied):
            self.open_trip(NOBODY, "TRIP-B")
        with self.assertRaises(Denied):
            self.summary_trip_ids(NOBODY)
        self.as_user(NOBODY)
        with self.assertRaises(Denied):
            self.dashboard.get_dashboard_data()

    # ---- root cause and migrate fix ----------------------------------------
    def test_drifted_site_reproduces_reported_error_for_admin(self):
        self.simulate_drifted_site()
        self.as_user(ADMIN)
        with self.assertRaises(Denied) as raised:
            self.page.get_trip_telemetry_details("TRIP-B")
        self.assertEqual(str(raised.exception), "No permission for NetraNext Journey TRIP-B")
        self.assertEqual(self.summary_trip_ids(ADMIN), {"TRIP-ADM"})
        self.assertEqual(self.history_trip_ids(ADMIN), {"TRIP-ADM"})

    def test_migrate_patch_restores_admin_access_and_keeps_emp_scoped(self):
        self.simulate_drifted_site()
        self.access_patch.execute()
        self.assertEqual(self.model.property_setters, [])
        admin_rows = [r for r in self.model.custom_docperms[JOURNEY] if r["role"] == "NetraNext Admin"]
        self.assertEqual(len(admin_rows), 1)
        self.assertEqual(admin_rows[0]["read"], 1)
        self.assertEqual(self.open_trip(ADMIN, "TRIP-B")["employee_id"], "EMP-B")
        self.assertEqual(self.open_trip(ADMIN, "TRIP-ATT")["trip_id"], "TRIP-ATT")
        self.assertEqual(self.summary_trip_ids(ADMIN), set(self.trips))
        self.assertEqual(self.history_trip_ids(ADMIN), set(self.trips))
        with self.assertRaises(Denied):
            self.open_trip(ALICE, "TRIP-B")
        self.assertEqual(self.summary_trip_ids(ALICE), {"TRIP-A"})
        self.access_patch.execute()  # idempotent
        self.assertEqual(len([r for r in self.model.custom_docperms[JOURNEY]
                              if r["role"] == "NetraNext Admin"]), 1)

    def test_patch_does_not_freeze_standard_permissions(self):
        self.access_patch.execute()
        self.assertEqual(self.model.custom_docperms, {})

    def test_patch_creates_missing_role(self):
        self.roles_on_site.discard("NetraNext Admin")
        self.access_patch.execute()
        self.assertIn("NetraNext Admin", self.roles_on_site)

    def test_doctype_json_hooks_and_patch_registration(self):
        meta = json.loads(JOURNEY_JSON.read_text())
        admin = [r for r in meta["permissions"] if r["role"] == "NetraNext Admin"]
        self.assertTrue(admin and admin[0]["read"] and not admin[0].get("if_owner"))
        employee = next(f for f in meta["fields"] if f["fieldname"] == "employee")
        self.assertEqual(employee.get("ignore_user_permissions"), 1)
        self.assertIn("NetraNext Admin", self.policy.MANAGER_ROLES)
        for doctype in self.policy.EMPLOYEE_OWNED_DOCTYPES:
            self.assertTrue(registered_hook("has_permission", doctype))
            self.assertTrue(registered_hook("permission_query_conditions", doctype))
        post_sync = (ROOT / "patches.txt").read_text().split("[post_model_sync]")[1]
        self.assertIn("netranext_client.netranext.patches.ensure_netranext_admin_record_access", post_sync)


if __name__ == "__main__":
    unittest.main()
