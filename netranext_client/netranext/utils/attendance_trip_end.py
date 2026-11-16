"""Shift-end reminder, snooze and automatic end for attendance-based trips.

No new records: the trip-end schedule lives in the same private session
context on Employee Checkin (`custom_netra_trip_context`, key `trip_end`)
that already owns the attendance trip, and the trip is ended through the
same `_write_journey` -> `store_journey` path as check-out.

Timeline for one session (all times naive, in the site's time zone):

    shift end S ......... reminder "Your Shift Has Ended"  (stage shift_end)
    S + 1 h ............. deadline: the trip is ended automatically
    employee snoozes N h at T (1/2/3 h, at most `max_snoozes()` times):
    T + N h ............. reminder "Your Trip Is Still Active" (stage snooze_followup)
    T + N h + 1 h ....... new deadline

`version` increases whenever the schedule changes (shift moved before it
ended, or a snooze was accepted). Reminders and snooze requests carry the
version they were issued for, so stale notifications, late or repeated
jobs and concurrent snoozes from two devices can never act on an outdated
deadline. Only the latest deadline exists; there is never more than one
countdown per trip.

Automatic ending ends the JOURNEY only. It never creates an attendance
check-out: the session stays checked in (`closed` stays false) and is
marked `auto_ended`, so attendance and trip status remain distinguishable.
A later check-out closes the session and keeps the journey's auto-end time.

Every function expects the employee row lock (attendance_journey.
lock_employee) to be held by its caller.
"""
import re
from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime

from netranext_client.netranext.utils import attendance_journey as aj

END_REASON = 'AUTO_SHIFT_END_TIMEOUT'
GRACE = timedelta(hours=1)
SNOOZE_HOURS = (1, 2, 3)
DEFAULT_MAX_SNOOZES = 3
# A shift assignment can change until the shift ends; re-read it this often.
RECOMPUTE_EVERY = timedelta(minutes=5)
# A check-in outside any shift window uses the next shift starting within this.
FORWARD_SHIFT_WINDOW = timedelta(hours=12)
# Open sessions older than this are not scanned (overnight shift + snoozes fit).
SESSION_LOOKBACK = timedelta(days=2)
_REQUEST_ID = re.compile(r'^[A-Za-z0-9_.:-]{1,100}$')


def max_snoozes():
    try:
        return max(0, int(frappe.conf.get('netranext_trip_end_max_snoozes', DEFAULT_MAX_SNOOZES)))
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_MAX_SNOOZES


def _local(value):
    """Naive site-local datetime from a stored string / datetime."""
    dt = get_datetime(value)
    if dt is not None and dt.tzinfo is not None:
        dt = dt.astimezone(aj.system_zone()).replace(tzinfo=None)
    return dt


def iso(value):
    return aj._aware(_local(value)).isoformat() if value else None


def _shift_lookup(employee, when, direction=None):
    """HRMS shift containing `when` (or the next one with direction='forward'),
    including the employee's default shift. Patched in offline tests."""
    from hrms.hr.doctype.shift_assignment.shift_assignment import get_employee_shift
    return get_employee_shift(employee, when, True, direction)


def session_shift(context):
    """The shift this session belongs to: (end, name), or None (no shift)."""
    started = _local(context['started_at'])
    details = _shift_lookup(context['employee'], started)
    end = _local(details.get('end_datetime')) if details and details.get('end_datetime') else None
    if end is None or end <= started:
        details = _shift_lookup(context['employee'], started, 'forward')
        start = _local(details.get('start_datetime')) if details and details.get('start_datetime') else None
        end = _local(details.get('end_datetime')) if details and details.get('end_datetime') else None
        if start is None or end is None or start - started > FORWARD_SHIFT_WINDOW:
            return None
    if end <= started:
        return None
    shift_type = details.get('shift_type')
    name = shift_type.get('name') if isinstance(shift_type, dict) else shift_type
    return end, name


def is_active(context):
    """The session's trip is running: started, not checked out, not auto-ended."""
    return bool(context and context.get('started_at') and not context.get('closed')
                and not context.get('auto_ended'))


def journey_status(context):
    return frappe.db.get_value('NetraNext Journey',
        {'employee': context['employee'], 'flutter_journey_id': context['journey_id']}, 'status')


def refresh(checkin_id, context, now=None):
    """Create or update the session's shift-end schedule. Returns True when
    the context changed (and was saved).

    Before the shift-end reminder is due the shift is re-read (shift edits are
    honoured); from then on the countdown is frozen and only a snooze moves it.
    """
    now = now or now_datetime()
    if not is_active(context):
        return False
    state = dict(context.get('trip_end') or {})
    reminder_at = _local(state['reminder_at']) if state.get('reminder_at') else None
    if reminder_at and (state.get('stage') != 'shift_end' or now >= reminder_at):
        return False
    if state.get('computed_at') and now - _local(state['computed_at']) < RECOMPUTE_EVERY:
        return False
    shift = session_shift(context)
    state['computed_at'] = str(now)
    state.setdefault('version', 0)
    state.setdefault('snooze_count', 0)
    if shift is None:
        # No assigned/default shift: no shift-end reminder and no auto end.
        if state.get('reminder_at'):
            state['version'] += 1
        for key in ('reminder_at', 'deadline', 'shift_end', 'shift_name', 'stage'):
            state.pop(key, None)
        state['no_shift'] = True
    else:
        shift_end, shift_name = shift
        # Never start a countdown in the past (computed after an outage, or the
        # shift was moved to an already-passed end): the employee always gets
        # the full hour after the reminder.
        first_reminder = max(shift_end, now)
        if state.get('reminder_at') != str(first_reminder):
            state['version'] += 1
        state.update(no_shift=False, stage='shift_end', shift_name=shift_name, shift_end=str(shift_end),
                     reminder_at=str(first_reminder), deadline=str(first_reminder + GRACE))
    context['trip_end'] = state
    aj.save(checkin_id, context)
    return True


def summary(context, now=None):
    """Trip-end state for the app and the hub (wire format, ISO with offset)."""
    state = context.get('trip_end') or {}
    auto = context.get('auto_ended') or {}
    if not state and not auto:
        return None
    now = now or now_datetime()
    reminder_at = _local(state['reminder_at']) if state.get('reminder_at') else None
    count = int(state.get('snooze_count') or 0)
    limit = max_snoozes()
    return dict(
        version=int(state.get('version') or 0),
        stage=state.get('stage'),
        no_shift=bool(state.get('no_shift')),
        shift_end=iso(state.get('shift_end')),
        reminder_at=iso(state.get('reminder_at')),
        deadline=iso(state.get('deadline')),
        snooze_count=count,
        max_snoozes=limit,
        snooze_hours=list(SNOOZE_HOURS),
        snooze_allowed=bool(is_active(context) and reminder_at and state.get('shift_end')
                            and now >= _local(state['shift_end']) and count < limit),
        auto_ended=bool(auto),
        auto_ended_at=iso(auto.get('at')),
        end_reason=auto.get('reason'),
    )


def snooze(checkin_id, context, hours, version=None, request_id=None, now=None):
    """Extend the automatic end by 1, 2 or 3 hours from now.

    Idempotent per request_id; a request issued for an older schedule version
    (second device, stale notification) is not applied and simply returns the
    current schedule. Returns a dict(applied=bool, reason=str|None).
    """
    now = now or now_datetime()
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        hours = None
    if hours not in SNOOZE_HOURS:
        frappe.throw('Choose a snooze of 1, 2 or 3 hours.')
    if request_id is not None and not _REQUEST_ID.match(str(request_id)):
        frappe.throw('Invalid snooze request.')
    state = dict(context.get('trip_end') or {})
    snoozes = list(state.get('snoozes') or [])
    if request_id and any(item.get('request_id') == request_id for item in snoozes):
        return dict(applied=False, reason='duplicate')
    if context.get('closed'):
        frappe.throw('You have already checked out. This trip has ended.')
    if context.get('auto_ended') or not context.get('started_at') or journey_status(context) != 'In Progress':
        frappe.throw('This trip has already ended.')
    if not state.get('shift_end') or now < _local(state['shift_end']):
        frappe.throw('The trip end can be snoozed only after your shift has ended.')
    if version not in (None, '') and int(version) != int(state.get('version') or 0):
        return dict(applied=False, reason='stale')
    if int(state.get('snooze_count') or 0) >= max_snoozes():
        frappe.throw('The snooze limit for this trip has been reached. Please check out to end your trip.')
    until = now + timedelta(hours=hours)
    snoozes.append(dict(hours=hours, accepted_at=str(now), until=str(until), request_id=request_id))
    state.update(stage='snooze_followup', reminder_at=str(until), deadline=str(until + GRACE),
                 snooze_count=int(state.get('snooze_count') or 0) + 1,
                 version=int(state.get('version') or 0) + 1, snoozes=snoozes[-10:])
    context['trip_end'] = state
    aj.save(checkin_id, context)
    return dict(applied=True, reason=None)


def _end_point(context, end_time):
    """Last recorded GPS point at or before the automatic end time."""
    raw = frappe.db.get_value('NetraNext Journey',
        {'employee': context['employee'], 'flutter_journey_id': context['journey_id']}, 'raw_gps_data')
    try:
        points = aj.unpack(raw)
    except ValueError:
        points = []
    for point in reversed(points if isinstance(points, list) else []):
        when = aj._point_time(point.get('timestamp')) if isinstance(point, dict) else None
        if when is not None and when <= end_time:
            return dict(latitude=point.get('latitude'), longitude=point.get('longitude'))
    return None


def auto_end_if_due(checkin_id, context, now=None):
    """End the session's journey when its latest deadline has passed.

    Rechecks everything at execution time: a check-out recorded meanwhile
    (including exactly at the deadline) wins and nothing is auto-ended; an
    already ended journey is left untouched; a newer snooze deadline is the
    only deadline there is. Returns True when the journey was ended.
    """
    now = now or now_datetime()
    if not is_active(context):
        return False
    state = context.get('trip_end') or {}
    if not state.get('deadline') or now < _local(state['deadline']):
        return False
    if aj._reconcile_open(checkin_id, context):
        return False  # a recorded check-out ended the session first
    if journey_status(context) != 'In Progress':
        return False
    end_time = _local(state['deadline'])
    previous = dict(context)
    context.update(
        auto_ended=dict(reason=END_REASON, at=str(end_time), executed_at=str(now),
                        version=int(state.get('version') or 0)),
        end_time=str(end_time), end_point=_end_point(context, end_time))
    # The end photo stays pending (never invented, never copied from the
    # start reading); the employee can still submit it from the dashboard.
    context['pending_end'] = bool(context.get('odometer_required') and not context.get('end_photo_received'))
    aj.save(checkin_id, context)
    try:
        aj._write_journey(checkin_id, context)
    except Exception:
        aj.save(checkin_id, previous)  # retried by the next scheduler run
        raise
    aj.tenant_bench_logger.info(
        f"Attendance trip {context['journey_id']} ended automatically at {end_time} "
        f"({END_REASON}, executed {now}, version {state.get('version')})", 'ATTENDANCE_TRIP')
    return True


def _open_sessions(now):
    rows = frappe.get_all('Employee Checkin', filters={
        'log_type': 'IN', aj.CONTEXT_FIELD: ['is', 'set'], 'time': ['>', now - SESSION_LOOKBACK]},
        fields=['name', 'employee'], order_by='time desc')
    seen = set()
    for row in rows:
        if row.employee in seen:
            continue  # only the employee's latest session can own a running trip
        seen.add(row.employee)
        yield row


def _each_open_session(now, fn):
    """Run fn(checkin_id, context) for every open session under its employee
    lock, committing per employee so one failure never blocks the others."""
    results = []
    for row in _open_sessions(now):
        try:
            aj.lock_employee(row.employee)
            checkin_id, context = aj.latest(row.employee)
            if checkin_id != row.name or not is_active(context):
                frappe.db.commit()
                continue
            result = fn(checkin_id, context)
            frappe.db.commit()
            if result is not None:
                results.append(result)
        except Exception:
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), 'Attendance Trip End')
    return results


def process_due_auto_ends():
    """Scheduler job (every minute): keep schedules current and end overdue
    trips. Runs on the tenant bench, so trips end on time even when the hub,
    the push service or the employee's phone is unavailable."""
    now = now_datetime()

    def step(checkin_id, context):
        refresh(checkin_id, context, now)
        auto_end_if_due(checkin_id, context, now)
    _each_open_session(now, step)


def upcoming_reminders(lookahead_minutes=360):
    """Reminder occurrences for the hub's discovery job: every running trip
    whose current reminder is due within the look-ahead and whose deadline
    has not passed."""
    now = now_datetime()
    horizon = now + timedelta(minutes=lookahead_minutes)

    def step(checkin_id, context):
        refresh(checkin_id, context, now)
        state = context.get('trip_end') or {}
        if not state.get('reminder_at') or state.get('no_shift'):
            return None
        reminder_at, deadline = _local(state['reminder_at']), _local(state['deadline'])
        if reminder_at > horizon or now >= deadline:
            return None
        return dict(employee_id=context['employee'],
                    employee_name=frappe.db.get_value('Employee', context['employee'], 'employee_name'),
                    user_id=frappe.db.get_value('Employee', context['employee'], 'user_id') or context.get('user_id'),
                    checkin_id=checkin_id, journey_id=context['journey_id'],
                    stage=state.get('stage'), version=int(state.get('version') or 0),
                    reminder_at_iso=iso(reminder_at), deadline_iso=iso(deadline),
                    timezone=str(aj.system_zone()))
    return _each_open_session(now, step)


def validate_reminder(kind, checkin_id, version=None, expected_user_id=None):
    """Send-time validation for the hub dispatcher. Returns
    dict(valid=bool, reason=str|None, ...details)."""
    employee = frappe.db.get_value('Employee Checkin', checkin_id, 'employee') if checkin_id else None
    if not employee:
        return dict(valid=False, reason='session_not_found')
    aj.lock_employee(employee)
    checkin_id, context = aj.latest(employee, checkin_id)
    if not context:
        return dict(valid=False, reason='session_not_found')
    aj._reconcile_open(checkin_id, context)  # a check-out the hook missed
    user_id = frappe.db.get_value('Employee', employee, 'user_id') or context.get('user_id')
    if expected_user_id and str(user_id or '').lower() != str(expected_user_id).lower():
        return dict(valid=False, reason='recipient_changed')
    if context.get('closed'):
        return dict(valid=False, reason='checked_out')
    if context.get('auto_ended'):
        return dict(valid=False, reason='trip_already_ended')
    if not context.get('started_at') or journey_status(context) != 'In Progress':
        return dict(valid=False, reason='trip_not_active')
    details = dict(employee_id=employee, employee_name=frappe.db.get_value('Employee', employee, 'employee_name'),
                   checkin_id=checkin_id, journey_id=context['journey_id'])
    if kind == 'odometer_start':
        if not context.get('odometer_required') or not context.get('pending_start'):
            return dict(valid=False, reason='start_odometer_not_pending')
        return dict(details, valid=True, reason=None)
    if kind != 'trip_end':
        return dict(valid=False, reason='unknown_kind')
    refresh(checkin_id, context)
    state = context.get('trip_end') or {}
    if not state.get('reminder_at') or state.get('no_shift'):
        return dict(valid=False, reason='no_shift')
    if version not in (None, '') and int(version) != int(state.get('version') or 0):
        return dict(valid=False, reason='superseded')
    if now_datetime() < _local(state['reminder_at']) - timedelta(minutes=1):
        return dict(valid=False, reason='not_due')
    return dict(details, valid=True, reason=None, **summary(context))
