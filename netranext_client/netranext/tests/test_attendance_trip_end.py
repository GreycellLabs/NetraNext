"""Shift-end reminder, snooze and automatic end of attendance trips.

Runs the real attendance_journey + attendance_trip_end + store_journey against
the in-memory Frappe boundary used by test_attendance_journey (no bench, no
database, no HRMS: the shift lookup is replaced per test).
"""
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import test_attendance_journey as base  # noqa: E402  (module import: its tests are not re-collected)
from _frappe_fake import set_clock  # noqa: E402

DAY = (2026, 11, 4)


def at(hour, minute=0, day=4):
    return datetime(2026, 11, day, hour, minute)


class TripEndTests(unittest.TestCase):
    setUp_base = base.AttendanceJourneyTests.setUp
    checkin = base.AttendanceJourneyTests.checkin
    claim_reminder = base.AttendanceJourneyTests.claim_reminder
    context = base.AttendanceJourneyTests.context
    journey = base.AttendanceJourneyTests.journey

    def setUp(self):
        self.setUp_base()
        self.frappe.db.rollback = lambda: None
        self.end = base.load('netranext_client.netranext.utils.attendance_trip_end', ROOT / 'utils/attendance_trip_end.py')
        sys.modules['netranext_client.netranext.utils'].attendance_trip_end = self.end
        self.shift = dict(start=at(9), end=at(18))
        self.end._shift_lookup = self.lookup

    def lookup(self, employee, when, direction=None):
        if self.shift is None:
            return None
        if direction is None and not (self.shift['start'] <= when <= self.shift['end']):
            return None
        return dict(start_datetime=self.shift['start'], end_datetime=self.shift['end'], shift_type='Day Shift')

    # helpers -----------------------------------------------------------------
    def tick(self, when):
        set_clock(when)
        self.end.process_due_auto_ends()

    def snooze(self, hours, when, version=None, request_id=None):
        set_clock(when)
        if version is None:
            version = self.context()['trip_end']['version']
        return self.api.store_journey(dict(employee_id=self.employee, attendance_action='snooze_trip_end',
            attendance_checkin='IN1', hours=hours, version=version, request_id=request_id or f'req-{when:%H%M}-{hours}'))

    def checkout(self, when, name='OUT1'):
        set_clock(when)
        self.frappe.get_doc(dict(doctype='Employee Checkin', name=name, employee=self.employee,
                                 log_type='OUT', time=when)).insert()
        return self.base_checkout(when, name)

    def base_checkout(self, when, name):
        return self.helper.handle_checkout_stored(dict(employee_id=self.employee, time=str(when)), name)

    def state(self):
        return self.api.store_journey(dict(employee_id=self.employee, attendance_action='state'))['data']['context']

    def started(self):
        self.checkin()
        self.tick(at(9, 1))
        return self.context()['trip_end']

    # schedule -----------------------------------------------------------------
    def test_shift_end_schedules_reminder_and_one_hour_deadline(self):
        state = self.started()
        self.assertEqual(state['reminder_at'], '2026-11-04 18:00:00')
        self.assertEqual(state['deadline'], '2026-11-04 19:00:00')
        self.assertEqual(state['stage'], 'shift_end')
        self.assertEqual(state['version'], 1)
        summary = self.state()['trip_end']
        self.assertEqual(summary['deadline'], '2026-11-04T19:00:00+00:00')
        self.assertFalse(summary['snooze_allowed'], 'not before the shift ends')

    def test_no_assigned_shift_never_reminds_or_auto_ends(self):
        self.shift = None
        self.checkin()
        self.tick(at(9, 1))
        self.assertTrue(self.context()['trip_end']['no_shift'])
        self.tick(at(23, 59))
        self.assertEqual(self.journey()['status'], 'In Progress')
        set_clock(at(18))
        self.assertEqual(self.end.upcoming_reminders(), [])

    def test_overnight_shift_ends_on_the_next_day(self):
        self.shift = dict(start=at(8), end=at(2, day=5))
        state = self.started()
        self.assertEqual(state['deadline'], '2026-11-05 03:00:00')
        self.tick(at(23, 59))
        self.assertEqual(self.journey()['status'], 'In Progress')
        self.tick(at(3, 0, day=5))
        self.assertEqual(self.journey()['status'], 'Completed')

    def test_shift_change_before_its_end_moves_the_reminder_then_freezes(self):
        self.started()
        self.shift = dict(start=at(9), end=at(17))
        self.tick(at(9, 7))
        state = self.context()['trip_end']
        self.assertEqual((state['reminder_at'], state['version']), ('2026-11-04 17:00:00', 2))
        self.shift = dict(start=at(9), end=at(20))
        self.tick(at(17, 30))  # countdown already running: frozen
        self.assertEqual(self.context()['trip_end']['deadline'], '2026-11-04 18:00:00')

    # automatic end ------------------------------------------------------------
    def test_initial_deadline_ends_trip_without_checking_out(self):
        self.started()
        self.tick(at(18, 59))
        self.assertEqual(self.journey()['status'], 'In Progress')
        self.tick(at(19, 0))
        context = self.context()
        self.assertEqual(self.journey()['status'], 'Completed')
        self.assertEqual(self.journey()['end_time'], '2026-11-04 19:00:00')
        self.assertFalse(context['closed'], 'attendance stays checked in')
        self.assertEqual(context['auto_ended']['reason'], 'AUTO_SHIFT_END_TIMEOUT')
        self.assertEqual(json.loads(self.journey()['metadata'])['attendance']['end_reason'], 'AUTO_SHIFT_END_TIMEOUT')
        self.assertEqual([c['log_type'] for c in self.store.get('Employee Checkin')], ['IN'], 'no checkout created')
        payload = self.state()
        self.assertTrue(payload['auto_ended'])
        self.assertEqual(payload['end_reason'], 'AUTO_SHIFT_END_TIMEOUT')

    def test_late_or_repeated_scheduler_runs_end_once_at_the_deadline(self):
        self.started()
        self.tick(at(21, 30))  # worker was down
        first = dict(self.context()['auto_ended'])
        self.tick(at(21, 31))
        self.tick(at(22, 0))
        self.assertEqual(self.context()['auto_ended'], first)
        self.assertEqual(first['at'], '2026-11-04 19:00:00')
        self.assertEqual(first['executed_at'], '2026-11-04 21:30:00')
        self.assertEqual(self.journey()['end_time'], '2026-11-04 19:00:00')

    def test_state_refresh_is_a_backstop_for_the_scheduler(self):
        self.checkin()
        set_clock(at(9, 1))
        self.assertEqual(self.state()['trip_end']['deadline'], '2026-11-04T19:00:00+00:00')
        set_clock(at(19, 5))  # every-minute scheduler never ran
        self.assertTrue(self.state()['auto_ended'])

    def test_schedule_first_computed_after_shift_end_still_gives_a_full_hour(self):
        self.checkin()
        self.tick(at(19, 5))  # scheduler was down from check-in until after the shift
        self.assertEqual(self.journey()['status'], 'In Progress')
        self.assertEqual(self.context()['trip_end']['deadline'], '2026-11-04 20:05:00')

    def test_checkout_during_countdown_cancels_auto_end(self):
        self.started()
        self.checkout(at(18, 30))
        self.tick(at(19, 0))
        context = self.context()
        self.assertNotIn('auto_ended', context)
        self.assertEqual(self.journey()['end_time'], '2026-11-04 18:30:00')

    def test_checkout_recorded_exactly_at_deadline_wins_even_if_its_hook_missed(self):
        self.started()
        set_clock(at(19))
        self.frappe.get_doc(dict(doctype='Employee Checkin', name='OUT1', employee=self.employee,
                                 log_type='OUT', time=at(19))).insert()
        self.tick(at(19))
        context = self.context()
        self.assertTrue(context['closed'])
        self.assertNotIn('auto_ended', context)

    def test_checkout_after_auto_end_keeps_the_trip_end_time(self):
        self.started()
        self.tick(at(19))
        self.checkout(at(20, 15))
        context = self.context()
        self.assertTrue(context['closed'])
        self.assertEqual(context['checkout_time'], '2026-11-04 20:15:00')
        self.assertEqual(self.journey()['end_time'], '2026-11-04 19:00:00')

    def test_app_syncs_after_auto_end_neither_reopen_nor_check_out(self):
        self.started()
        self.tick(at(19))
        sync = dict(employee_id=self.employee, journey_id='attendance-IN1', tracking_source='attendance_auto',
                    attendance_checkin='IN1', start_time='2026-11-04 09:00:00')
        self.api.store_journey(dict(sync, status='In Progress'))
        self.assertEqual(self.journey()['status'], 'Completed')
        self.api.store_journey(dict(sync, status='Completed', end_time='2026-11-04 19:20:00'))
        self.assertEqual(self.journey()['end_time'], '2026-11-04 19:00:00')
        self.assertFalse(self.context()['closed'])
        self.assertEqual(json.loads(self.journey()['metadata'])['attendance']['end_reason'], 'AUTO_SHIFT_END_TIMEOUT')

    def test_auto_end_leaves_end_odometer_pending_and_accepts_it_later(self):
        self.checkin()
        self.api.store_journey(dict(employee_id=self.employee, attendance_action='start_photo', attendance_checkin='IN1',
                                    start_odometer=100, start_odometer_photo='image', start_odometer_source='manual'))
        self.tick(at(9, 1))
        self.tick(at(19))
        context = self.context()
        self.assertTrue(context['pending_end'])
        self.assertIsNone(self.journey().get('end_odometer'), 'never invented or copied from the start')
        result = self.api.store_journey(dict(employee_id=self.employee, attendance_action='end_photo',
            attendance_checkin='IN1', end_odometer=180, end_odometer_photo='image', end_odometer_source='manual'))
        self.assertEqual(result['status'], 'success')
        self.assertEqual(self.journey()['end_odometer'], 180.)
        self.assertFalse(self.context()['pending_end'])

    def test_manual_trips_are_never_auto_ended(self):
        self.started()
        self.store.get('NetraNext Journey')[0]['status'] = 'Completed'  # trip ended some other way
        self.frappe.get_doc(dict(doctype='NetraNext Journey', name='MANUAL', employee=self.employee,
                                 flutter_journey_id='manual-1', tracking_source='manual', status='In Progress',
                                 journey_name='m', start_time='2026-11-04 10:00:00')).insert()
        self.tick(at(19))
        self.assertNotIn('auto_ended', self.context())
        manual = [j for j in self.store.get('NetraNext Journey') if j['name'] == 'MANUAL'][0]
        self.assertEqual(manual['status'], 'In Progress')

    # snooze ------------------------------------------------------------------
    def test_snooze_one_two_three_hours_from_acceptance(self):
        for hours, expected in ((1, '2026-11-04 19:10:00'), (2, '2026-11-04 20:10:00'), (3, '2026-11-04 21:10:00')):
            with self.subTest(hours=hours):
                self.store.get('Employee Checkin').clear()
                self.store.get('NetraNext Journey').clear()
                self.started()
                result = self.snooze(hours, at(18, 10))
                self.assertTrue(result['data']['applied'])
                state = self.context()['trip_end']
                self.assertEqual(state['reminder_at'], expected)
                self.assertEqual(state['stage'], 'snooze_followup')

    def test_snoozed_trip_runs_past_old_deadline_and_ends_after_followup_grace(self):
        self.started()
        self.snooze(2, at(18, 10))
        self.tick(at(19))
        self.assertEqual(self.journey()['status'], 'In Progress', 'old deadline superseded')
        self.tick(at(21, 9))
        self.assertEqual(self.journey()['status'], 'In Progress')
        self.tick(at(21, 10))
        self.assertEqual(self.journey()['end_time'], '2026-11-04 21:10:00')

    def test_repeat_snooze_and_limit(self):
        self.started()
        self.snooze(1, at(18, 10))
        self.snooze(1, at(19, 10))
        self.snooze(1, at(20, 10))
        self.assertEqual(self.context()['trip_end']['snooze_count'], 3)
        result = self.snooze(1, at(21, 10))
        self.assertEqual(result['status'], 'error')
        self.assertIn('limit', result['message'])
        self.assertFalse(self.state()['trip_end']['snooze_allowed'])

    def test_duplicate_and_concurrent_stale_snoozes_apply_once(self):
        self.started()
        version = self.context()['trip_end']['version']
        first = self.snooze(2, at(18, 10), version=version, request_id='tap-1')
        retry = self.snooze(2, at(18, 11), version=version, request_id='tap-1')
        other_device = self.snooze(3, at(18, 11), version=version, request_id='tap-2')
        self.assertTrue(first['data']['applied'])
        self.assertEqual(retry['data']['reason'], 'duplicate')
        self.assertEqual(other_device['data']['reason'], 'stale')
        state = self.context()['trip_end']
        self.assertEqual((state['snooze_count'], state['reminder_at']), (1, '2026-11-04 20:10:00'))

    def test_snooze_rejected_before_shift_end_after_checkout_and_for_bad_hours(self):
        self.started()
        self.assertEqual(self.snooze(1, at(17))['status'], 'error')
        self.assertEqual(self.snooze(4, at(18, 5))['status'], 'error')
        self.checkout(at(18, 20))
        self.assertIn('checked out', self.snooze(1, at(18, 30))['message'])

    def test_checkout_during_snooze_stops_everything(self):
        self.started()
        self.snooze(1, at(18, 10))
        self.checkout(at(18, 40))
        self.tick(at(23))
        self.assertNotIn('auto_ended', self.context())
        set_clock(at(19, 10))
        self.assertEqual(self.end.validate_reminder('trip_end', 'IN1')['reason'], 'checked_out')

    # hub discovery / validation ----------------------------------------------
    def test_discovery_and_send_time_validation(self):
        self.started()
        set_clock(at(17, 0))
        [occurrence] = self.end.upcoming_reminders(360)
        self.assertEqual(occurrence['reminder_at_iso'], '2026-11-04T18:00:00+00:00')
        self.assertEqual(occurrence['user_id'], 'one@example.com')
        version = occurrence['version']
        set_clock(at(18))
        valid = self.end.validate_reminder('trip_end', 'IN1', version, 'one@example.com')
        self.assertTrue(valid['valid'])
        self.assertTrue(valid['snooze_allowed'])
        self.assertEqual(self.end.validate_reminder('trip_end', 'IN1', version, 'x@example.com')['reason'],
                         'recipient_changed')
        self.snooze(1, at(18, 5))
        self.assertEqual(self.end.validate_reminder('trip_end', 'IN1', version)['reason'], 'superseded')
        set_clock(at(19, 5))
        followup = self.end.validate_reminder('trip_end', 'IN1', version + 1)
        self.assertEqual((followup['valid'], followup['stage']), (True, 'snooze_followup'))
        self.tick(at(20, 5))
        set_clock(at(20, 6))
        self.assertEqual(self.end.validate_reminder('trip_end', 'IN1', version + 1)['reason'], 'trip_already_ended')

    def test_start_odometer_reminder_validation_and_one_time_claim(self):
        self.checkin()
        self.assertTrue(self.end.validate_reminder('odometer_start', 'IN1')['valid'])
        self.assertTrue(self.claim_reminder()['data']['claimed'])
        again = self.claim_reminder(claim_id='claim-2')
        self.assertFalse(again['data']['claimed'])
        self.assertTrue(again['data']['suppressed'])
        self.api.store_journey(dict(employee_id=self.employee, attendance_action='start_photo', attendance_checkin='IN1',
                                    start_odometer=100, start_odometer_photo='image', start_odometer_source='manual'))
        self.assertEqual(self.end.validate_reminder('odometer_start', 'IN1')['reason'], 'start_odometer_not_pending')

    def test_new_checkin_session_gets_its_own_independent_schedule(self):
        self.started()
        self.snooze(1, at(18, 10))
        self.checkout(at(18, 30))
        self.shift = dict(start=at(9, day=5), end=at(18, day=5))
        set_clock(at(9, 0, day=5))
        self.frappe.get_doc(dict(doctype='Employee Checkin', name='IN2', employee=self.employee,
                                 log_type='IN', time=at(9, 0, day=5))).insert()
        self.helper.handle_checkin_stored(dict(employee_id=self.employee, latitude=12., longitude=77.,
                                               tracking_accuracy=8), 'IN2')
        self.tick(at(9, 1, day=5))
        _, context = self.helper.latest(self.employee, 'IN2')
        self.assertEqual(context['trip_end']['snooze_count'], 0)
        self.assertEqual(context['trip_end']['deadline'], '2026-11-05 19:00:00')
        self.assertNotIn('start_reminder', context)


if __name__ == '__main__':
    unittest.main()
