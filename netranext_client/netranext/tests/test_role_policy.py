"""NetraNext Admin vs Employee access contract, without a bench.

Real trip_permissions policy against a stubbed role/Employee lookup, plus the
DocType permission rows and migration patches that grant the role.
Run: python3 -m unittest discover -s netranext/tests -p test_role_policy.py
"""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ADMIN = 'NetraNext Admin'

ROLES = {
    'admin@x': [ADMIN],
    'adminemp@x': [ADMIN, 'Employee'],
    'emp@x': ['Employee'],
    'other@x': ['Employee'],
    'hr@x': ['HR Manager'],
    'nobody@x': [],
}
EMPLOYEES = {'EMP-ADMIN': 'adminemp@x', 'EMP-1': 'emp@x', 'EMP-2': 'other@x'}


class PermissionError_(Exception):
    pass


def fake_frappe():
    frappe = types.ModuleType('frappe')
    frappe.session = types.SimpleNamespace(user='emp@x')
    frappe.PermissionError = PermissionError_
    frappe.get_roles = lambda user: list(ROLES.get(user, []))

    def exists(doctype, filters):
        if doctype != 'Employee':
            return None
        return any(name == filters.get('name') and user == filters.get('user_id') for name, user in EMPLOYEES.items()) or None
    frappe.db = types.SimpleNamespace(exists=exists, escape=lambda v: repr(v))

    def throw(msg, exc=Exception):
        raise exc(msg)
    frappe.throw = throw
    return frappe


def load_policy():
    spec = importlib.util.spec_from_file_location('trip_permissions_under_test', ROOT / 'utils' / 'trip_permissions.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RolePolicyTests(unittest.TestCase):
    def setUp(self):
        self.frappe = fake_frappe()
        self.patcher = patch.dict(sys.modules, {'frappe': self.frappe})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.policy = load_policy()

    def test_netranext_admin_is_a_manager(self):
        self.assertTrue(self.policy.is_trip_manager('admin@x'))

    def test_admin_plus_employee_gets_admin_access(self):
        self.assertTrue(self.policy.is_trip_manager('adminemp@x'))
        self.assertEqual(self.policy.get_permission_query_conditions('adminemp@x'), '')
        self.assertTrue(self.policy.can_access_employee('EMP-2', 'adminemp@x'))

    def test_employee_only_is_limited_to_own_records(self):
        self.assertFalse(self.policy.is_trip_manager('emp@x'))
        self.assertTrue(self.policy.can_access_employee('EMP-1', 'emp@x'))
        self.assertFalse(self.policy.can_access_employee('EMP-2', 'emp@x'))
        self.assertIn("'emp@x'", self.policy.get_permission_query_conditions('emp@x'))
        other_trip = types.SimpleNamespace(employee='EMP-2')
        own_trip = types.SimpleNamespace(employee='EMP-1')
        self.assertIs(self.policy.has_permission(other_trip, 'emp@x'), False)
        self.assertIsNone(self.policy.has_permission(own_trip, 'emp@x'))

    def test_admin_reads_any_employee_trip(self):
        trip = types.SimpleNamespace(employee='EMP-2')
        self.assertIsNone(self.policy.has_permission(trip, 'admin@x'))  # no veto
        self.assertTrue(self.policy.can_access_employee('EMP-1', 'admin@x'))

    def test_existing_hr_roles_keep_access(self):
        self.assertTrue(self.policy.is_trip_manager('hr@x'))

    def test_no_role_and_guest_are_denied(self):
        self.assertFalse(self.policy.is_trip_manager('nobody@x'))
        self.assertFalse(self.policy.can_access_employee('EMP-1', 'nobody@x'))
        self.assertFalse(self.policy.can_access_employee('EMP-1', 'Guest'))
        self.assertEqual(self.policy.get_permission_query_conditions('Guest'), '1=0')


class EmployeeRecordHookTests(RolePolicyTests.__base__):
    """Approval/request DocTypes share the Journey ownership rule."""
    HOOKED = {
        'face_checkin_approval_conditions': 'NetraNext Face Checkin Approval',
        'location_checkin_approval_conditions': 'NetraNext Location Checkin Approval',
        'face_registration_request_conditions': 'NetraNext Face Registration Request',
    }

    def setUp(self):
        self.frappe = fake_frappe()
        self.patcher = patch.dict(sys.modules, {'frappe': self.frappe})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.policy = load_policy()

    def test_managers_unscoped_employees_own_only_guest_nothing(self):
        for fn, doctype in self.HOOKED.items():
            with self.subTest(doctype=doctype):
                conditions = getattr(self.policy, fn)
                self.assertEqual(conditions('adminemp@x'), '')
                self.assertEqual(conditions('admin@x'), '')
                own = conditions('emp@x')
                self.assertTrue(own.startswith(f'`tab{doctype}`.`employee` IN'))
                self.assertIn("'emp@x'", own)
                self.assertEqual(conditions('Guest'), '1=0')

    def test_hooks_registered_and_user_permission_bypass_only_where_hooked(self):
        hooks = (ROOT.parent / 'hooks.py').read_text()
        for fn, doctype in self.HOOKED.items():
            self.assertIn(f'"{doctype}": "netranext_client.netranext.utils.trip_permissions.{fn}"', hooks)
            self.assertIn(f'"{doctype}": "netranext_client.netranext.utils.trip_permissions.has_permission"', hooks)
        for folder in ('netranext_journey', 'netranext_face_checkin_approval',
                       'netranext_location_checkin_approval', 'netranext_face_registration_request'):
            doc = json.loads((ROOT / 'doctype' / folder / f'{folder}.json').read_text())
            employee = next(f for f in doc['fields'] if f['fieldname'] == 'employee')
            self.assertEqual(employee.get('ignore_user_permissions'), 1, folder)
        # Scheduled Trip grants All rwcd: bypassing User Permissions there
        # would expose every trip to every user, so it must stay restricted.
        doc = json.loads((ROOT / 'doctype' / 'scheduled_trip' / 'scheduled_trip.json').read_text())
        employee = next(f for f in doc['fields'] if f['fieldname'] == 'employee')
        self.assertFalse(employee.get('ignore_user_permissions'))


class DocTypeGrantTests(unittest.TestCase):
    """The role must be granted on the NetraNext DocTypes it administers."""
    EXPECTED = {
        'netranext_journey': {'read', 'write', 'create', 'delete'},
        'netranext_settings': {'read', 'write'},
        'netranext_face_checkin_approval': {'read', 'write', 'create', 'delete'},
        'netranext_location_checkin_approval': {'read', 'write', 'create', 'delete'},
        'netranext_location': {'read', 'write', 'create', 'delete'},
        'netranext_face_registration_request': {'read', 'write', 'create', 'delete'},
        'netranext_user_mapping': {'read', 'write', 'create', 'delete'},
        'scheduled_trip': {'read', 'write', 'create', 'delete'},
        'netranext_sync_log': {'read'},
        'netranext_assignment_outbox': {'read'},
    }

    def test_admin_rows_present(self):
        for folder, expected in self.EXPECTED.items():
            with self.subTest(doctype=folder):
                doc = json.loads((ROOT / 'doctype' / folder / f'{folder}.json').read_text())
                rows = [p for p in doc['permissions'] if p['role'] == ADMIN]
                self.assertEqual(len(rows), 1)
                granted = {k for k in ('read', 'write', 'create', 'delete') if rows[0].get(k)}
                self.assertEqual(granted, expected)

    def test_employee_role_is_not_widened(self):
        doc = json.loads((ROOT / 'doctype' / 'netranext_settings' / 'netranext_settings.json').read_text())
        self.assertFalse([p for p in doc['permissions'] if p['role'] == 'Employee'])

    def test_role_is_created_before_doctype_sync(self):
        text = (ROOT.parent / 'patches.txt').read_text()
        pre, post = text.split('[post_model_sync]')
        self.assertIn('patches.create_netranext_admin_role', pre)
        self.assertIn('patches.grant_netranext_admin_attendance_read', post)


if __name__ == '__main__':
    unittest.main()
