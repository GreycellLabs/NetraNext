"""Dispatch revalidation rejects stale Scheduled Trip assignments."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class AssignmentValidationTests(unittest.TestCase):
    def setUp(self):
        self.frappe = MagicMock()
        self.frappe.whitelist = lambda **kw: lambda fn: fn
        self.frappe.PermissionError = PermissionError
        self.frappe.db.exists.return_value = True
        self.frappe.get_doc.return_value = {
            'allocated_to': 'employee@example.com', 'status': 'Open',
            'reference_type': 'Scheduled Trip', 'reference_name': 'SCHED-1',
        }
        self.frappe.get_all.side_effect = [
            [types.SimpleNamespace(status='Relayed')],
            [types.SimpleNamespace(event_id='EVENT-NEW')],
        ]
        self.frappe.db.get_value.side_effect = [
            types.SimpleNamespace(employee='EMP-1', status='Scheduled'),
            'employee@example.com',
        ]
        modules = patch.dict(sys.modules, {'frappe': self.frappe})
        modules.start()
        self.addCleanup(modules.stop)
        path = Path(__file__).resolve().parents[1] / 'netranext_client/netranext/apis/v1/todo.py'
        spec = importlib.util.spec_from_file_location('validation_test', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module._validate_integration = lambda: 'tenant-1'
        self.module._resolve_user = lambda value: value
        self.module._active_employee_exists = lambda value: True
        self.module._todo_summary = lambda todo: {'reference_name': 'SCHED-1'}

    def validate(self, event='EVENT-NEW'):
        return self.module.validate_assignment_event(event, 'TD-1', 'employee@example.com')['data']

    def test_current_assignment_is_valid(self):
        self.assertTrue(self.validate()['valid'])

    def test_older_generation_is_superseded_even_for_same_recipient(self):
        self.assertEqual(self.validate('EVENT-OLD')['reason'], 'superseded')

    def test_completed_or_cancelled_trip_is_not_deliverable(self):
        for status in ('Completed', 'Cancelled'):
            with self.subTest(status=status):
                self.frappe.get_all.side_effect = [[types.SimpleNamespace(status='Relayed')], [types.SimpleNamespace(event_id='EVENT-NEW')]]
                self.frappe.db.get_value.side_effect = [types.SimpleNamespace(employee='EMP-1', status=status)]
                self.assertEqual(self.validate()['reason'], 'trip_not_actionable')

    def test_legacy_open_todo_for_old_employee_is_rejected(self):
        self.frappe.db.get_value.side_effect = [types.SimpleNamespace(employee='EMP-2', status='Scheduled'), 'other@example.com']
        self.assertEqual(self.validate()['reason'], 'trip_reassigned')
