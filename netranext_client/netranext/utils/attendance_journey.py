"""Attendance triggers for the existing Journey API; no separate trip records.

One private JSON context lives on Employee Checkin. All journey writes use
sync.store_journey, including check-out. This module exposes no HTTP methods.
"""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_datetime, now_datetime

CONTEXT_FIELD = 'custom_netra_trip_context'
REASON = 'Attendance-Based Automatic Start'


def enabled():
    return bool(int(frappe.db.get_single_value('NetraNext Settings', 'enable_auto_attendance_trip_tracking') or 0))


def unpack(value):
    return json.loads(value) if isinstance(value, str) and value else (value or {})


def epoch_ms(value):
    dt = get_datetime(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(frappe.utils.get_system_timezone()))
    return dt.timestamp() * 1000


def local_time(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).astimezone(
        ZoneInfo(frappe.utils.get_system_timezone())).replace(tzinfo=None)


def lock_employee(employee):
    frappe.db.sql('SELECT name FROM `tabEmployee` WHERE name=%s FOR UPDATE', employee)


def latest(employee, checkin_id=None):
    filters = {'employee': employee, 'log_type': 'IN', CONTEXT_FIELD: ['is', 'set']}
    if checkin_id:
        filters['name'] = checkin_id
    rows = frappe.get_all('Employee Checkin', filters=filters,
                          fields=['name', CONTEXT_FIELD], order_by='time desc, creation desc', limit=1)
    if not rows:
        return None, {}
    return rows[0].name, unpack(rows[0].get(CONTEXT_FIELD))


def save(checkin_id, context):
    frappe.db.set_value('Employee Checkin', checkin_id, CONTEXT_FIELD,
                        json.dumps(context, default=str), update_modified=False)


def payload(checkin_id, context):
    # Photos remain attached files; the dashboard only needs their status.
    result = {k: v for k, v in dict(context, checkin_id=checkin_id, enabled=enabled()).items()
              if k not in ('start_photo', 'late_start_photo')}
    result['late_start_photo_received'] = bool(context.get('late_start_photo'))
    for key in ('started_at', 'end_time'):
        if result.get(key):
            dt = get_datetime(result[key])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo(frappe.utils.get_system_timezone()))
            result[key] = dt.isoformat()
    return result


def _write_journey(checkin_id, context, initial=False):
    """Use the same Journey persistence as manual start, sync and end."""
    from netranext_client.netranext.apis.v1.sync import store_journey
    data = dict(employee_id=context['employee'], user_id=context.get('user_id'),
        journey_id=context['journey_id'], attendance_checkin=checkin_id,
        tracking_source='attendance_auto', start_time=context['started_at'],
        status='Completed' if context.get('closed') else 'In Progress')
    if initial:
        point = context['anchor']
        data.update(start_location=f"{point['latitude']}, {point['longitude']}",
                    raw_gps_data=json.dumps([dict(point, label='Start')]))
    if context.get('closed'):
        data['end_time'] = context['end_time']
        point = context.get('end_point') or {}
        if point.get('latitude') is not None and point.get('longitude') is not None:
            data['end_location'] = f"{point['latitude']}, {point['longitude']}"
    result = store_journey(data)
    if result.get('status') != 'success':
        frappe.throw(result.get('message') or 'Unable to save attendance-linked journey.')


def _ensure_started(checkin_id, context):
    """Idempotent check-in trigger, with no departure or movement gate."""
    if context.get('closed'):
        return
    existing = frappe.db.get_value('NetraNext Journey',
        {'employee': context['employee'], 'flutter_journey_id': context['journey_id']}, 'name')
    if existing:
        return  # A replay must not replace an existing route or start time.
    if not enabled():
        return
    conflict = frappe.db.get_value('NetraNext Journey',
        {'employee': context['employee'], 'status': 'In Progress'}, 'name')
    if conflict:
        frappe.throw('Another trip is already in progress. End it before starting an attendance trip.')
    point = context['anchor']
    if point.get('latitude') is None or point.get('longitude') is None:
        frappe.throw('Attendance check-in has no location.')
    # Always use the saved check-in instant, even when recovering a failed
    # start or a session created by the former movement-monitor version.
    context.update(started_at=str(local_time(float(point['timestamp']))), start_point=point)
    context.pop('start_error', None)
    save(checkin_id, context)
    try:
        _write_journey(checkin_id, context, initial=True)
    except Exception:
        context.pop('started_at', None)
        context.pop('start_point', None)
        raise


def _try_start(checkin_id, context):
    try:
        _ensure_started(checkin_id, context)
    except Exception as exc:
        context['start_error'] = str(exc)
        frappe.log_error(frappe.get_traceback(), 'Attendance Journey Start')
        save(checkin_id, context)


def handle_checkin_stored(data, checkin_id):
    if not enabled():
        return None
    employee = data['employee_id']
    lock_employee(employee)
    previous_id, previous = latest(employee)
    if previous_id and previous_id != checkin_id and previous and not previous.get('closed'):
        # Duplicate check-in cannot reserve a second automatic journey or
        # overwrite the original check-in location/evidence.
        _try_start(previous_id, previous)
        return payload(previous_id, previous)
    checkin = frappe.get_doc('Employee Checkin', checkin_id)
    if checkin.get('custom_face_status') in ('Pending Approval', 'Rejected') or checkin.get('custom_location_status') in ('Pending Approval', 'Rejected'):
        return None
    current = unpack(checkin.get(CONTEXT_FIELD))
    if current:
        _try_start(checkin_id, current)
        return payload(checkin_id, current)
    required = bool(int(frappe.db.get_single_value('NetraNext Settings', 'enable_odometer_reading') or 0))
    context = dict(enabled=True, employee=employee,
        user_id=frappe.db.get_value('Employee', employee, 'user_id'),
        anchor=dict(latitude=data.get('latitude'), longitude=data.get('longitude'),
                    accuracy=data.get('tracking_accuracy'), timestamp=epoch_ms(checkin.time)),
        closed=False, journey_id='attendance-' + checkin_id,
        odometer_required=required, pending_start=required, pending_end=False)
    save(checkin_id, context)
    _try_start(checkin_id, context)
    return payload(checkin_id, context)


def handle_checkout_stored(data, checkout_id):
    employee = data['employee_id']
    lock_employee(employee)
    checkin_id, context = latest(employee)
    if not context:
        return None
    if epoch_ms(data['time']) < float(context['anchor']['timestamp']):
        return None  # A delayed checkout must not close a newer check-in.
    # Finish an owned automatic Journey even if settings changed mid-trip.
    if not context.get('closed'):
        context.update(closed=True, checkout_id=checkout_id, end_time=str(data['time']),
                       end_point=dict(latitude=data.get('latitude'), longitude=data.get('longitude')))
        context['pending_end'] = bool(context.get('odometer_required') and context.get('started_at') and not context.get('end_photo_received'))
    save(checkin_id, context)
    name = frappe.db.get_value('NetraNext Journey',
        {'employee': employee, 'flutter_journey_id': context['journey_id']}, 'name')
    if name:
        _write_journey(checkin_id, context)
    return payload(checkin_id, context)


def prepare_auto_sync(data):
    """Validate ownership and enforce server-held chronology/evidence."""
    employee = data['employee_id']
    checkin_id = data.get('attendance_checkin')
    if not checkin_id:
        frappe.throw('Automatic journey requires its attendance check-in.')
    checkin_id, context = latest(employee, checkin_id)
    if not context or not context.get('started_at') or data.get('journey_id') != context.get('journey_id'):
        frappe.throw('Journey does not match its attendance check-in.')
    existing = frappe.db.get_value('NetraNext Journey',
        {'employee': employee, 'flutter_journey_id': context['journey_id']}, 'name')
    if not existing:
        conflict = frappe.db.get_value('NetraNext Journey', {'employee': employee, 'status': 'In Progress'}, 'name')
        if conflict:
            frappe.throw('Another trip is already in progress.')
    from netranext_client.netranext.apis.v1.sync import _validate_odometer_sources, _save_odometer_photo
    from netranext_client.netranext.utils.odometer_units import normalize_odometer_fields
    # Start evidence belongs to the stored attendance context, never a stale heartbeat.
    end_evidence = {k: v for k, v in data.items() if k.startswith('end_odometer')}
    normalize_odometer_fields(end_evidence)
    data.update(end_evidence)
    _validate_odometer_sources({k: data[k] for k in ('end_odometer', 'end_odometer_source') if k in data})
    if data.get('end_odometer') is not None and data.get('end_odometer_photo'):
        previous_photo = frappe.db.get_value('NetraNext Journey', existing, 'end_odometer_photo') if existing else None
        photo = previous_photo if previous_photo and data['end_odometer_photo'] == previous_photo else _save_odometer_photo(data['end_odometer_photo'], context['journey_id'], 'end')
        if not photo:
            frappe.throw('End odometer photo could not be saved.')
        data['end_odometer_photo'] = photo
    data['start_time'] = context['started_at']
    data['attendance_checkin'] = checkin_id
    if data.get('status') == 'Completed' and not context.get('closed'):
        context.update(closed=True, end_time=str(data.get('end_time') or now_datetime()),
                       pending_end=bool(context.get('odometer_required')))
    if context.get('closed'):
        data.update(status='Completed', end_time=context['end_time'])
    # Dashboard capture happens after check-in starts the trip. Persist that
    # evidence on this same Journey and keep it authoritative on later syncs.
    for field in ('start_odometer', 'start_odometer_photo', 'start_odometer_source', 'start_odometer_original', 'start_odometer_unit'):
        data.pop(field, None)
    if not context.get('pending_start') and context.get('start_photo'):
        data.update(start_odometer=context['start_reading'], start_odometer_photo=context['start_photo'],
                    start_odometer_source=context['start_source'])
        if context.get('start_unit'):
            data.update(start_odometer_original=context['start_original'], start_odometer_unit=context['start_unit'])
    if data.get('end_odometer') is not None and data.get('end_odometer_photo'):
        if context.get('start_reading') is not None and float(data['end_odometer']) < float(context['start_reading']):
            frappe.throw('End odometer cannot be below start odometer.')
        context['pending_end'] = False
        context['end_photo_received'] = True
        context['end_source'] = data.get('end_odometer_source')
    save(checkin_id, context)
    metadata = unpack(data.get('metadata') or (frappe.db.get_value('NetraNext Journey', existing, 'metadata') if existing else None))
    metadata['attendance'] = dict(checkin_id=checkin_id, odometer_required=context.get('odometer_required'),
        pending_start=context.get('pending_start'), pending_end=context.get('pending_end'),
        start_source=context.get('start_source'), end_source=context.get('end_source'),
        late_start_photo=context.get('late_start_photo'))
    data['metadata'] = json.dumps(metadata)
    data['reason'] = REASON
    return context


def action(data):
    """Small actions on the existing store_journey request contract."""
    employee = data['employee_id']
    lock_employee(employee)
    checkin_id, context = latest(employee, data.get('attendance_checkin'))
    operation = data['attendance_action']
    if operation == 'state':
        if context and not context.get('closed'):
            _try_start(checkin_id, context)
        return dict(context=payload(checkin_id, context) if context else None, enabled=enabled())
    if not context:
        frappe.throw('No attendance check-in to update.')
    if operation == 'start_photo':
        if context.get('closed'):
            frappe.throw('Start odometer photo can only be submitted while checked in.')
        from netranext_client.netranext.apis.v1.sync import _save_odometer_photo, _validate_odometer_sources
        from netranext_client.netranext.utils.odometer_units import normalize_odometer_fields
        normalize_odometer_fields(data)
        reading = data.get('start_odometer')
        if reading is None or not data.get('start_odometer_photo'):
            frappe.throw('An odometer reading and photo are required.')
        value = float(reading)
        if not 0 <= value <= 9999999 * 1.609344:
            frappe.throw('Invalid odometer reading.')
        _validate_odometer_sources(data)
        photo = _save_odometer_photo(data['start_odometer_photo'], context['journey_id'], 'start')
        if not photo:
            frappe.throw('Odometer photo could not be saved.')
        previous = dict(context)
        context.update(start_photo=photo, start_reading=value,
                       start_source=data.get('start_odometer_source'),
                       start_original=data.get('start_odometer_original'), start_unit=data.get('start_odometer_unit'),
                       start_captured_at=str(now_datetime()), pending_start=False)
        save(checkin_id, context)
        if context.get('started_at'):
            try:
                _write_journey(checkin_id, context)
            except Exception:
                save(checkin_id, previous)
                raise
    elif operation == 'confirm':
        # Compatibility for old apps: confirmation is now an idempotent
        # check-in start, and the former GPS fixes are deliberately ignored.
        if context.get('closed'):
            frappe.throw('Attendance is already checked out.')
        _ensure_started(checkin_id, context)
    else:
        frappe.throw('Unknown attendance journey action.')
    return dict(context=payload(checkin_id, context), enabled=enabled())
