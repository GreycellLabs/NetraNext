"""ToDo assignment transition detection and outbox relay regressions (no live DB).

Covers the tenant-side half of the ToDo assignment push feature:
- events/todo_assignment.py — which ToDo transitions produce a logical
  assignment event (and which must never produce one),
- utils/assignment_outbox.py — relay outcome classification, bounded
  retry/backoff and the crash-isolation contract (a notification problem
  must never break the assignment or its transaction).

Run with the bench environment's python -m unittest discover -s tests.
"""
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import requests

ROOT = Path(__file__).resolve().parents[1] / 'netranext_client' / 'netranext'
NOW = datetime(2026, 10, 26, 12, 0, 0)


class FakeToDo:
    def __init__(self, name, allocated_to, status='Open', assigned_by='boss@tenant.example',
                 reference_type='Task', reference_name='TASK-1', before=None):
        self.name = name
        self._data = {
            'allocated_to': allocated_to,
            'status': status,
            'assigned_by': assigned_by,
            'reference_type': reference_type,
            'reference_name': reference_name,
        }
        self._before = before

    def get(self, key, default=None):
        return self._data.get(key, default)

    def get_doc_before_save(self):
        return self._before


def fake_add_to_date(value, days=0, hours=0, minutes=0, seconds=0, **kwargs):
    return value + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


class AssignmentEventTests(unittest.TestCase):
    def setUp(self):
        self.frappe = MagicMock()
        self.frappe.db.get_single_value.return_value = 'tenant-a'
        self.frappe.db.exists.return_value = False
        self.frappe.get_all.return_value = []
        self.frappe.utils.now_datetime.return_value = NOW
        self.frappe.utils.add_to_date.side_effect = fake_add_to_date
        self.inserted = []
        self.frappe.get_doc.side_effect = lambda payload: (self.inserted.append(payload), MagicMock())[1]
        modules = patch.dict(sys.modules, {'frappe': self.frappe})
        modules.start()
        self.addCleanup(modules.stop)
        self.module = self.load('events/todo_assignment.py', 'todo_events_test')

    def load(self, relative, name):
        spec = importlib.util.spec_from_file_location(name, ROOT / relative)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def inserted_doc(self, index=0):
        self.assertTrue(self.inserted, 'expected an outbox insert')
        return self.inserted[index]

    def test_event_id_is_stable_and_scoped(self):
        base = self.module._assignment_event_id('TD0001', 1, 'user@tenant.example')
        again = self.module._assignment_event_id('TD0001', 1, 'USER@Tenant.Example')
        self.assertEqual(base, again)  # recipient normalised, same logical event
        self.assertTrue(base.startswith('TAE-'))
        self.assertEqual(len(base), 4 + 24)
        for variant in [
            self.module._assignment_event_id('TD0002', 1, 'user@tenant.example'),  # other todo
            self.module._assignment_event_id('TD0001', 2, 'user@tenant.example'),  # new generation
            self.module._assignment_event_id('TD0001', 1, 'other@tenant.example'),  # other recipient
        ]:
            self.assertNotEqual(base, variant)

    def test_after_insert_records_open_assignment(self):
        self.module.on_todo_after_insert(FakeToDo('TD0001', 'user@tenant.example'))
        doc = self.inserted_doc()
        self.assertEqual(doc['doctype'], self.module.OUTBOX_DOCTYPE)
        self.assertEqual(doc['recipient'], 'user@tenant.example')
        self.assertEqual(doc['todo_name'], 'TD0001')
        self.assertEqual(doc['assignment_generation'], 1)
        self.assertEqual(doc['status'], 'Pending')
        self.assertEqual(doc['relay_deadline'], NOW + timedelta(hours=self.module.RELAY_WINDOW_HOURS))
        self.frappe.enqueue.assert_called_once()
        self.assertTrue(self.frappe.enqueue.call_args.kwargs.get('enqueue_after_commit'))

    def test_self_assignment_produces_no_event(self):
        self.module.on_todo_after_insert(
            FakeToDo('TD0001', 'user@tenant.example', assigned_by='user@tenant.example'))
        self.assertFalse(self.inserted)

    def test_unassigned_or_closed_insert_produces_no_event(self):
        self.module.on_todo_after_insert(FakeToDo('TD0001', ''))
        self.module.on_todo_after_insert(FakeToDo('TD0002', 'user@tenant.example', status='Closed'))
        self.assertFalse(self.inserted)

    def test_duplicate_event_id_is_not_recorded_twice(self):
        self.frappe.db.exists.return_value = True
        self.module.on_todo_after_insert(FakeToDo('TD0001', 'user@tenant.example'))
        self.assertFalse(self.inserted)

    def test_generation_counts_recorded_transitions(self):
        self.frappe.get_all.return_value = [types.SimpleNamespace(assignment_generation=2)]
        self.module.on_todo_after_insert(FakeToDo('TD0001', 'user@tenant.example'))
        self.assertEqual(self.inserted_doc()['assignment_generation'], 3)

    def test_reassignment_invalidates_previous_recipient_and_records_new(self):
        invalidated = []

        def get_all_router(*args, **kwargs):
            filters = kwargs.get('filters') or {}
            if 'pluck' in kwargs:  # invalidation discovery query
                invalidated.append(filters)
                return ['ASSN-OUT-00001']
            return [types.SimpleNamespace(assignment_generation=1)]  # generation query

        self.frappe.get_all.side_effect = get_all_router
        before = FakeToDo('TD0001', 'first@tenant.example')
        self.module.on_todo_update(FakeToDo('TD0001', 'second@tenant.example', before=before))
        self.assertEqual(invalidated, [{'todo_name': 'TD0001', 'status': 'Pending', 'recipient': 'first@tenant.example'}])
        self.frappe.db.set_value.assert_called_once_with(
            self.module.OUTBOX_DOCTYPE, 'ASSN-OUT-00001',
            {'status': 'Invalidated', 'last_error': 'reassigned'})
        self.assertEqual(self.inserted_doc()['recipient'], 'second@tenant.example')
        self.assertEqual(self.inserted_doc()['assignment_generation'], 2)

    def test_closure_invalidates_without_recipient_scope(self):
        captured = []

        def get_all_router(*args, **kwargs):
            filters = kwargs.get('filters') or {}
            if 'pluck' in kwargs:
                captured.append(filters)
                return ['ASSN-OUT-00002']
            return []

        self.frappe.get_all.side_effect = get_all_router
        before = FakeToDo('TD0001', 'user@tenant.example', status='Open')
        self.module.on_todo_update(FakeToDo('TD0001', 'user@tenant.example', status='Closed', before=before))
        self.assertEqual(captured, [{'todo_name': 'TD0001', 'status': 'Pending'}])
        self.assertIn('todo_closed', str(self.frappe.db.set_value.call_args))
        self.assertFalse(self.inserted)

    def test_unassignment_invalidates(self):
        self.frappe.get_all.side_effect = lambda *a, **k: ['ASSN-OUT-00003'] if 'pluck' in k else []
        before = FakeToDo('TD0001', 'user@tenant.example')
        self.module.on_todo_update(FakeToDo('TD0001', '', before=before))
        self.assertIn('todo_unassigned', str(self.frappe.db.set_value.call_args))

    def test_reopen_after_close_records_a_fresh_generation_event(self):
        self.frappe.get_all.return_value = [types.SimpleNamespace(assignment_generation=1)]
        before = FakeToDo('TD0001', 'user@tenant.example', status='Closed')
        self.module.on_todo_update(FakeToDo('TD0001', 'user@tenant.example', status='Open', before=before))
        self.assertEqual(self.inserted_doc()['assignment_generation'], 2)

    def test_ordinary_edit_emits_nothing(self):
        before = FakeToDo('TD0001', 'user@tenant.example', status='Open')
        self.module.on_todo_update(
            FakeToDo('TD0001', 'user@tenant.example', status='Open', before=before))
        self.assertFalse(self.inserted)
        self.frappe.get_all.assert_not_called()
        self.frappe.db.set_value.assert_not_called()

    def test_update_without_before_save_state_is_a_noop(self):
        self.module.on_todo_update(FakeToDo('TD0001', 'user@tenant.example', before=None))
        self.assertFalse(self.inserted)

    def test_trash_invalidates_all_pending_events(self):
        self.frappe.get_all.return_value = ['ASSN-OUT-00004']
        self.module.on_todo_trash(FakeToDo('TD0001', 'user@tenant.example'))
        self.frappe.db.set_value.assert_called_once_with(
            self.module.OUTBOX_DOCTYPE, 'ASSN-OUT-00004',
            {'status': 'Invalidated', 'last_error': 'todo_deleted'})

    def test_hook_failures_never_break_the_todo_save(self):
        self.frappe.get_doc.side_effect = RuntimeError('outbox down')
        self.module.on_todo_after_insert(FakeToDo('TD0001', 'user@tenant.example'))
        before = FakeToDo('TD0001', 'first@tenant.example')
        self.module.on_todo_update(FakeToDo('TD0001', 'second@tenant.example', before=before))
        self.frappe.get_doc.side_effect = None
        self.frappe.get_all.side_effect = RuntimeError('db down')
        self.module.on_todo_trash(FakeToDo('TD0001', 'user@tenant.example'))  # must not raise


class AssignmentRelayTests(unittest.TestCase):
    def setUp(self):
        self.frappe = MagicMock()
        self.frappe.utils.now_datetime.return_value = NOW
        self.frappe.utils.get_datetime.side_effect = lambda value: value
        self.frappe.utils.cstr.side_effect = str
        self.frappe.utils.add_to_date.side_effect = fake_add_to_date
        settings = MagicMock()
        settings.get_password.return_value = 'integration-token'
        settings.central_server_url = 'https://service.example'
        settings.tenant_id = 'tenant-a'
        self.frappe.get_single.return_value = settings
        modules = patch.dict(sys.modules, {'frappe': self.frappe})
        modules.start()
        self.addCleanup(modules.stop)
        spec = importlib.util.spec_from_file_location(
            'todo_relay_test', ROOT / 'utils' / 'assignment_outbox.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.event = types.SimpleNamespace(
            name='ASSN-OUT-00001', status='Pending', event_id='TAE-' + 'a' * 24,
            todo_name='TD0001', reference_type='Task', reference_name='TASK-1',
            recipient='user@tenant.example', assigned_by='boss@tenant.example',
            assignment_generation=1, occurred_at=NOW, attempts=0,
            relay_deadline=NOW + timedelta(hours=24))
        self.frappe.get_doc.side_effect = lambda *a, **k: self.event

    def post(self, status_code=200, body=None):
        response = MagicMock(status_code=status_code)
        response.json.return_value = body if body is not None else {'message': {'status': 'success'}}
        return patch.object(self.module.requests, 'post', return_value=response)

    def set_value(self):
        self.frappe.db.set_value.assert_called_once()
        args = self.frappe.db.set_value.call_args.args
        return args[0], args[1], args[2]

    def test_accepted_event_is_marked_relayed(self):
        with self.post() as post:
            self.module._relay_one(self.event.name, NOW)
        self.assertIn('receive_assignment_event', post.call_args.args[0])
        headers = post.call_args.kwargs['headers']
        self.assertEqual(headers['X-Tenant-ID'], 'tenant-a')
        self.assertEqual(headers['X-NetraNext-Token'], 'integration-token')
        self.assertEqual(post.call_args.kwargs['json']['event_id'], self.event.event_id)
        doctype, name, values = self.set_value()
        self.assertEqual((doctype, name), (self.module.OUTBOX_DOCTYPE, self.event.name))
        self.assertEqual(values['status'], 'Relayed')
        self.assertEqual(values['attempts'], 1)
        self.assertEqual(values['relayed_at'], NOW)

    def test_client_rejection_is_terminal(self):
        body = {'message': {'status': 'error', 'message': 'unknown tenant'}}
        with self.post(status_code=403, body=body):
            self.module._relay_one(self.event.name, NOW)
        _, _, values = self.set_value()
        self.assertEqual(values['status'], 'Failed')
        self.assertTrue(values['last_error'].startswith('rejected: HTTP 403'))
        self.assertIn('unknown tenant', values['last_error'])

    def test_throttling_and_server_errors_stay_retriable(self):
        for status in (429, 500, 503):
            self.frappe.db.set_value.reset_mock()
            with self.post(status_code=status, body={'message': {}}):
                self.module._relay_one(self.event.name, NOW)
            _, _, values = self.set_value()
            self.assertEqual(values['attempts'], 1)
            self.assertNotIn('status', values)  # stays Pending
            self.assertGreater(values['next_attempt_at'], NOW)

    def test_transport_failure_retries_with_backoff(self):
        with patch.object(self.module.requests, 'post', side_effect=requests.ConnectionError('refused')):
            self.module._relay_one(self.event.name, NOW)
        _, _, values = self.set_value()
        self.assertEqual(values['attempts'], 1)
        self.assertTrue(values['last_error'].startswith('transport:'))
        self.assertGreater(values['next_attempt_at'], NOW)

    def test_deadline_exceeded_fails_without_calling_the_service(self):
        self.event.relay_deadline = NOW - timedelta(seconds=1)
        with patch.object(self.module.requests, 'post') as post:
            self.module._relay_one(self.event.name, NOW)
        post.assert_not_called()
        _, _, values = self.set_value()
        self.assertEqual(values['status'], 'Failed')
        self.assertEqual(values['last_error'], 'relay_deadline_exceeded')

    def test_unconfigured_credentials_wait_without_burning_attempts(self):
        self.frappe.get_single.return_value.get_password.return_value = ''
        with patch.object(self.module.requests, 'post') as post:
            self.module._relay_one(self.event.name, NOW)
        post.assert_not_called()
        _, _, values = self.set_value()
        self.assertEqual(values['attempts'], 0)
        self.assertGreater(values['next_attempt_at'], NOW)
        self.assertNotIn('status', values)

    def test_exhausted_attempts_are_marked_failed(self):
        self.event.attempts = self.module.MAX_ATTEMPTS - 1
        with self.post(status_code=500, body={'message': {}}):
            self.module._relay_one(self.event.name, NOW)
        _, _, values = self.set_value()
        self.assertEqual(values['status'], 'Failed')
        self.assertTrue(values['last_error'].startswith('attempts exhausted'))

    def test_invalidated_event_is_left_alone_between_discovery_and_relay(self):
        self.event.status = 'Invalidated'
        with patch.object(self.module.requests, 'post') as post:
            self.module._relay_one(self.event.name, NOW)
        post.assert_not_called()
        self.frappe.db.set_value.assert_not_called()

    def test_backoff_grows_exponentially_then_caps(self):
        def delay_for(attempts):
            self.frappe.db.set_value.reset_mock()
            self.event.attempts = attempts
            self.module._schedule_retry(self.event, NOW, 'test')
            seconds = (self.frappe.db.set_value.call_args.args[2]['next_attempt_at'] - NOW).total_seconds()
            return seconds

        self.assertAlmostEqual(delay_for(0), 45, delta=15)  # 60s band, full jitter
        self.assertAlmostEqual(delay_for(3), 360, delta=120)  # base 480, full jitter
        # attempts=6 (base 3840) is already capped at 30 minutes
        self.assertAlmostEqual(delay_for(6), 30 * 60 * 3 / 4, delta=30 * 60 / 4)
        # at MAX_ATTEMPTS the retry ladder ends in a terminal Failed state
        self.event.attempts = self.module.MAX_ATTEMPTS
        self.module._schedule_retry(self.event, NOW, 'test')
        self.assertEqual(self.frappe.db.set_value.call_args.args[2]['status'], 'Failed')

    def test_relay_sweep_commits_per_event_and_rolls_back_on_crash(self):
        self.frappe.get_all.return_value = ['ASSN-OUT-00001', 'ASSN-OUT-00002']
        outcomes = [None, RuntimeError('worker died')]
        with patch.object(self.module, '_relay_one', side_effect=outcomes):
            self.module.relay_pending_assignment_events()
        self.frappe.db.commit.assert_called_once()
        self.frappe.db.rollback.assert_called_once()
        filters = self.frappe.get_all.call_args.kwargs['filters']
        self.assertEqual(filters['status'], 'Pending')
        self.assertEqual(self.frappe.get_all.call_args.kwargs['limit'], self.module.BATCH_LIMIT)


if __name__ == '__main__':
    unittest.main()
