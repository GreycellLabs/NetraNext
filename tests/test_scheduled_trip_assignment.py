"""Scheduled Trip lifecycle regressions without a DB or push sends."""
import importlib.util
from datetime import datetime
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class TripAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.frappe = MagicMock()
        self.frappe.db.get_value.return_value = 'new@example.com'
        self.frappe.get_all.return_value = []
        self.frappe.session.user = 'manager@example.com'
        self.frappe.utils.getdate.side_effect = lambda value: str(value)[:10]
        modules = patch.dict(sys.modules, {
            'frappe': self.frappe,
            'frappe.model': types.ModuleType('frappe.model'),
            'frappe.model.document': types.SimpleNamespace(Document=object),
        })
        modules.start()
        self.addCleanup(modules.stop)
        path = Path(__file__).resolve().parents[1] / 'netranext_client/netranext/doctype/scheduled_trip/scheduled_trip.py'
        spec = importlib.util.spec_from_file_location('scheduled_trip_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.trip = module.ScheduledTrip()
        self.trip.name = 'SCHED-TEST'
        self.trip.employee = 'EMP-1'
        self.trip.status = 'Scheduled'
        self.trip.scheduled_start_time = datetime(2026, 11, 3, 9)

    def row(self, name, user='new@example.com', status='Open'):
        return types.SimpleNamespace(name=name, allocated_to=user, status=status)

    def test_new_assignment_uses_orm_and_accepts_datetime(self):
        self.trip.after_insert()
        payload = self.frappe.get_doc.call_args.args[0]
        self.assertEqual(payload['allocated_to'], 'new@example.com')
        self.assertEqual(payload['reference_name'], 'SCHED-TEST')
        self.assertEqual(payload['assigned_by'], 'manager@example.com')
        self.assertEqual(payload['date'], '2026-11-03')
        self.frappe.get_doc.return_value.insert.assert_called_once_with(ignore_permissions=True)

    def test_second_lifecycle_callback_does_not_duplicate(self):
        self.frappe.get_all.return_value = [self.row('TD-1')]
        self.trip.on_update()
        self.frappe.get_doc.assert_not_called()

    def test_historical_closed_duplicate_does_not_reopen_or_close_current(self):
        self.frappe.get_all.return_value = [self.row('TD-OLD', status='Closed'), self.row('TD-CURRENT')]
        self.trip.on_update()
        self.frappe.get_doc.assert_not_called()

    def test_reassignment_closes_old_and_inserts_new(self):
        self.frappe.get_all.return_value = [self.row('TD-OLD', 'old@example.com')]
        self.trip.on_update()
        self.assertEqual(self.frappe.get_doc.call_args_list[0].args, ('ToDo', 'TD-OLD'))
        self.frappe.get_doc.return_value.save.assert_called_once_with(ignore_permissions=True)
        self.assertEqual(self.frappe.get_doc.call_args.args[0]['allocated_to'], 'new@example.com')

    def test_rescheduling_reopens_existing_assignment(self):
        self.frappe.get_all.return_value = [self.row('TD-1', status='Closed')]
        self.trip.on_update()
        self.assertEqual(self.frappe.get_doc.return_value.status, 'Open')
        self.frappe.get_doc.return_value.save.assert_called_once_with(ignore_permissions=True)
        self.frappe.get_doc.return_value.insert.assert_not_called()

    def test_terminal_trip_closes_every_open_assignment(self):
        for status in ('Completed', 'Cancelled'):
            with self.subTest(status=status):
                self.frappe.get_doc.reset_mock()
                self.trip.status = status
                self.frappe.get_all.return_value = [self.row('TD-1'), self.row('TD-2', 'old@example.com')]
                self.trip.on_update()
                self.assertEqual(self.frappe.get_doc.return_value.save.call_count, 2)
                self.frappe.get_doc.return_value.insert.assert_not_called()

    def test_no_user_link_retires_old_assignment_without_creating(self):
        self.frappe.db.get_value.return_value = None
        self.frappe.get_all.return_value = [self.row('TD-OLD')]
        self.trip.on_update()
        self.assertEqual(self.frappe.get_doc.return_value.status, 'Closed')
        self.frappe.get_doc.return_value.insert.assert_not_called()

    def test_in_progress_does_not_create_assignment(self):
        self.trip.status = 'In Progress'
        self.trip.on_update()
        self.frappe.get_doc.assert_not_called()
