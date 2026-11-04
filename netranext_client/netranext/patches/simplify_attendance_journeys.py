"""Idempotent, non-destructive migration from retired automatic-trip records.

Creates one private field on Employee Checkin, not a DocType. Legacy tables
and attachments are retained; no DELETE/DROP occurs. Run via bench migrate.
"""
import json
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({'Employee Checkin': [dict(
        fieldname='custom_netra_trip_context', fieldtype='Long Text',
        label='NetraNext Journey Context', read_only=1, hidden=1, no_copy=1)]})
    if not frappe.db.table_exists('NetraNext Attendance Trip Session'):
        return
    from netranext_client.netranext.utils.attendance_journey import epoch_ms, save, unpack
    for session in frappe.db.sql('SELECT * FROM `tabNetraNext Attendance Trip Session` ORDER BY creation', as_dict=True):
        checkin_id = session.get('checkin_name')
        if not checkin_id or not frappe.db.exists('Employee Checkin', checkin_id):
            continue
        if frappe.db.get_value('Employee Checkin', checkin_id, 'custom_netra_trip_context'):
            continue
        required = bool(session.get('odometer_required'))
        context = dict(enabled=bool(session.get('auto_start_snapshot')), employee=session.employee,
            user_id=session.get('user_id'), journey_id=session.reserved_journey_id,
            anchor=dict(latitude=session.get('checkin_latitude'), longitude=session.get('checkin_longitude'),
                accuracy=session.get('checkin_accuracy'), timestamp=epoch_ms(session.checkin_time)),
            closed=session.status in ('completed', 'cancelled'),
            pending_start=required, pending_end=required and session.status == 'completed',
            odometer_required=required)
        if session.get('movement_confirmed_at'):
            context['started_at'] = str(session.movement_confirmed_at)
        if session.get('checkout_time'):
            context['end_time'] = str(session.checkout_time)
        if frappe.db.table_exists('NetraNext Trip Odometer Requirement'):
            for req in frappe.db.sql('SELECT * FROM `tabNetraNext Trip Odometer Requirement` WHERE session=%s', session.name, as_dict=True):
                if req.status in ('satisfied', 'waived', 'not_required'):
                    context['pending_' + req.kind] = False
                if req.kind == 'start' and req.get('evidence') and req.status == 'satisfied' and frappe.db.table_exists('NetraNext Trip Odometer Evidence'):
                    evidence = frappe.db.sql('SELECT photo_file, reading_value, source FROM `tabNetraNext Trip Odometer Evidence` WHERE name=%s', req.evidence, as_dict=True)
                    if evidence and evidence[0].get('photo_file'):
                        context.update(start_photo=evidence[0].photo_file, start_reading=evidence[0].reading_value,
                                       start_source=evidence[0].get('source'))
        if session.get('journey') and frappe.db.exists('NetraNext Journey', session.journey):
            journey = frappe.get_doc('NetraNext Journey', session.journey)
            points = unpack(journey.get('raw_gps_data')) or []
            context['start_point'] = points[0] if points else context['anchor']
            context['started_at'] = str(journey.start_time)
            if journey.get('end_time'):
                context['end_time'] = str(journey.end_time)
            if frappe.db.table_exists('NetraNext Trip Odometer Requirement'):
                for req in frappe.db.sql('SELECT * FROM `tabNetraNext Trip Odometer Requirement` WHERE session=%s', session.name, as_dict=True):
                    if req.status in ('satisfied', 'waived', 'not_required'):
                        context['pending_' + req.kind] = False
            if not context['pending_start'] and journey.get('start_odometer_photo'):
                context.update(start_reading=journey.get('start_odometer'), start_photo=journey.start_odometer_photo,
                    start_source=context.get('start_source') or unpack(journey.get('metadata')).get('flutter_data', {}).get('startOdometerSource'))
            metadata = unpack(journey.get('metadata'))
            metadata['attendance'] = dict(checkin_id=checkin_id, odometer_required=required,
                pending_start=context['pending_start'], pending_end=context['pending_end'])
            frappe.db.set_value('NetraNext Journey', journey.name,
                {'attendance_checkin': checkin_id, 'reason': 'Attendance-Based Automatic Start',
                 'metadata': json.dumps(metadata)}, update_modified=False)
        save(checkin_id, context)
