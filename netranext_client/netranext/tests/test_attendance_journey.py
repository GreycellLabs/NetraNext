"""Real attendance helper + store_journey with an in-memory Frappe boundary.

No HTTP, production DB, GPS device or Expense Claim insert is exercised.
"""
import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from _frappe_fake import build_fake, set_clock


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class AttendanceJourneyTests(unittest.TestCase):
    def setUp(self):
        self.frappe, utils, self.store = build_fake(settings={
            'enable_auto_attendance_trip_tracking': 1, 'enable_odometer_reading': 1,
            'allow_manual_odometer_edit': 1}, clock=datetime(2026, 11, 4, 9))
        self.frappe.utils = utils
        self.frappe._ = lambda text: text
        self.frappe.DuplicateEntryError = type('DuplicateEntryError', (Exception,), {})
        fields = json.loads((ROOT / 'doctype/netranext_journey/netranext_journey.json').read_text())['fields']
        self.frappe.get_meta = lambda dt: types.SimpleNamespace(fields=[types.SimpleNamespace(**f) for f in fields])
        modules = {'frappe': self.frappe, 'frappe.utils': utils}
        for name in ('netranext_client', 'netranext_client.netranext', 'netranext_client.netranext.utils',
                     'netranext_client.netranext.apis', 'netranext_client.netranext.apis.v1'):
            modules[name] = types.ModuleType(name)
        logger = types.ModuleType('logger');logger.tenant_bench_logger = MagicMock()
        errors = types.ModuleType('errors')
        for name in ('AuthenticationException','ValidationException','ResourceNotFoundException'):
            setattr(errors, name, type(name, (Exception,), {}))
        errors.handle_api_exception = lambda e, *a: dict(status='error', message=str(e))
        validators = types.ModuleType('validators')
        validators.validate_employee_exists = lambda *a: None
        validators.validate_required_fields = lambda *a: None
        modules.update({'netranext_client.netranext.utils.logger':logger,
                        'netranext_client.netranext.utils.error_handler':errors,
                        'netranext_client.netranext.utils.validators':validators})
        self.patcher = patch.dict(sys.modules, modules);self.patcher.start();self.addCleanup(self.patcher.stop)
        for name, file in [('odometer_units','utils/odometer_units.py'),('response_formatter','utils/response_formatter.py'),('movement_validation','utils/movement_validation.py')]:
            load('netranext_client.netranext.utils.'+name, ROOT/file)
        self.helper = load('netranext_client.netranext.utils.attendance_journey', ROOT/'utils/attendance_journey.py')
        sys.modules['netranext_client.netranext.utils'].attendance_journey = self.helper
        self.api = load('netranext_client.netranext.apis.v1.sync', ROOT/'apis/v1/sync.py')
        self.api._save_odometer_photo = lambda value,*a: '/files/photo.jpg' if value else None
        self.employee = 'EMP1'
        for doc in [dict(doctype='DocType',name='NetraNext Journey'),
                    dict(doctype='Employee',name='EMP1',user_id='one@example.com'),
                    dict(doctype='Employee',name='EMP2',user_id='two@example.com')]:
            self.frappe.get_doc(doc).insert()
        self.t0 = self.helper.epoch_ms(datetime(2026,11,4,9))

    def checkin(self, name='IN1'):
        self.frappe.get_doc(dict(doctype='Employee Checkin',name=name,employee=self.employee,
            log_type='IN',time=datetime(2026,11,4,9))).insert()
        return self.helper.handle_checkin_stored(dict(employee_id=self.employee,
            latitude=12.,longitude=77.,tracking_accuracy=8),name)

    def confirm(self, **kwargs):
        set_clock(datetime(2026,11,4,9,2))
        fixes=[dict(latitude=12.+m/111195,longitude=77.,accuracy=8,timestamp=self.t0+1000*t)
               for m,t in [(150,100),(175,110),(200,120)]]
        return self.api.store_journey(dict(employee_id=self.employee,attendance_action='confirm',
            attendance_checkin='IN1',fixes=fixes,**kwargs))

    def claim_reminder(self, **kwargs):
        set_clock(datetime(2026,11,4,9,2))
        fixes=[dict(latitude=12.+m/111195,longitude=77.,accuracy=8,timestamp=self.t0+1000*t)
               for m,t in [(150,100),(175,110),(200,120)]]
        request=dict(employee_id=self.employee,
            attendance_action='claim_start_odometer_reminder',attendance_checkin='IN1',
            reminder_kind='start',claim_id='claim-1',fixes=fixes)
        request.update(kwargs)
        return self.api.store_journey(request)

    def context(self):
        return self.helper.latest(self.employee,'IN1')[1]

    def journey(self):
        return self.store.get('NetraNext Journey')[0]

    def test_checkin_immediately_starts_existing_journey_at_checkin_location(self):
        context=self.checkin()
        self.assertTrue(context['pending_start'])
        self.assertEqual(context['checkin_id'],'IN1')
        self.assertEqual(len(self.store.get('NetraNext Journey')),1)
        self.assertEqual(self.journey()['status'],'In Progress')
        self.assertEqual(self.journey()['start_time'],'2026-11-04 09:00:00')
        self.assertEqual(self.journey()['start_location'],'12.0, 77.0')

    def test_automatic_journey_has_its_mandatory_journey_name(self):
        # journey_name is reqd on NetraNext Journey; the automatic start used
        # to omit it, so Frappe rejected the insert and no trip ever started.
        context=self.checkin()
        self.assertNotIn('start_error',context)
        self.assertTrue(context['started_at'])
        self.assertEqual(self.journey()['journey_name'],'Attendance Trip 2026-11-04 09:00')

    def test_site_time_zone_without_zoneinfo_data_still_starts_trip(self):
        # Ubuntu 24.04 tzdata drops legacy aliases such as Asia/Calcutta and
        # benches may lack the `tzdata` wheel: zoneinfo must not be needed.
        # (The legacy name itself is exercised on a real bench by
        # integration_tests/test_attendance_trip_live.py - the system pytz
        # this offline runner may use reads the same OS data.)
        import zoneinfo
        def no_zone_data(key):
            raise zoneinfo.ZoneInfoNotFoundError(key)
        with patch.object(self.frappe.utils,'get_system_timezone',lambda:'Asia/Kolkata'), \
             patch.object(zoneinfo,'ZoneInfo',no_zone_data):
            context=self.checkin()
            self.assertNotIn('start_error',context)
            self.assertEqual(self.journey()['status'],'In Progress')
            self.assertEqual(self.journey()['start_time'],'2026-11-04 09:00:00')
            self.assertTrue(context['started_at'].endswith('+05:30'),context['started_at'])
            start=json.loads(self.journey()['raw_gps_data'])[0]
            self.assertEqual(start['timestamp'],'2026-11-04T03:30:00.000Z')

    def test_checkin_start_point_uses_the_app_route_timestamp_format(self):
        # Desk Live Tracking formats point timestamps as strings; an epoch-ms
        # number made its rendering throw, hiding the new attendance trip.
        context=self.checkin()
        start=json.loads(self.journey()['raw_gps_data'])[0]
        self.assertIsInstance(start['timestamp'],str)
        self.assertRegex(start['timestamp'],r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$')
        self.assertEqual(self.helper._point_time(start['timestamp']),
                         self.helper.local_time(context['anchor']['timestamp']))
        self.assertEqual(start['label'],'Start')
        self.assertEqual((start['latitude'],start['longitude']),(12.0,77.0))

    def test_disabled_setting_changes_nothing(self):
        self.store.settings['enable_auto_attendance_trip_tracking']=0
        self.assertEqual(self.checkin(),{'skipped':'feature_disabled'})
        self.assertEqual(self.store.get('NetraNext Journey'),[])

    def test_pending_location_approval_skips_with_reason(self):
        self.frappe.get_doc(dict(doctype='Employee Checkin',name='IN1',employee=self.employee,
            log_type='IN',time=datetime(2026,11,4,9),custom_location_status='Pending Approval')).insert()
        result=self.helper.handle_checkin_stored(dict(employee_id=self.employee,
            latitude=12.,longitude=77.,tracking_accuracy=8),'IN1')
        self.assertEqual(result,{'skipped':'approval_pending'})
        self.assertEqual(self.store.get('NetraNext Journey'),[])
        self.assertFalse(self.helper.latest(self.employee,'IN1')[1])

    def test_start_after_approval_starts_the_trip(self):
        self.frappe.get_doc(dict(doctype='Employee Checkin',name='IN1',employee=self.employee,
            log_type='IN',time=datetime(2026,11,4,9),latitude=12.,longitude=77.,
            custom_location_status='Pending Approval')).insert()
        self.helper.handle_checkin_stored(dict(employee_id=self.employee,
            latitude=12.,longitude=77.,tracking_accuracy=8),'IN1')
        self.frappe.db.set_value('Employee Checkin','IN1','custom_location_status','Approved')
        payload=self.helper.start_after_approval('IN1')
        self.assertEqual(payload['journey_id'],'attendance-IN1')
        self.assertTrue(payload['started_at'])
        self.assertEqual(self.journey()['status'],'In Progress')
        self.assertEqual(self.journey()['attendance_checkin'],'IN1')
        # Replaying the approval trigger must not duplicate the trip.
        self.helper.start_after_approval('IN1')
        self.assertEqual(len(self.store.get('NetraNext Journey')),1)

    def test_start_after_approval_waits_for_face_approval_too(self):
        self.frappe.get_doc(dict(doctype='Employee Checkin',name='IN1',employee=self.employee,
            log_type='IN',time=datetime(2026,11,4,9),latitude=12.,longitude=77.,
            custom_location_status='Approved',
            custom_face_status='Pending Approval')).insert()
        self.assertEqual(self.helper.start_after_approval('IN1'),{'skipped':'approval_pending'})
        self.assertEqual(self.store.get('NetraNext Journey'),[])

    def test_confirm_uses_existing_journey_and_replay_is_idempotent(self):
        self.checkin()
        self.assertEqual(self.confirm()['status'],'success')
        self.assertEqual(self.confirm()['status'],'success')
        self.assertEqual(len(self.store.get('NetraNext Journey')),1)
        self.assertEqual(self.journey()['status'],'In Progress')
        self.assertEqual(self.journey()['reason'],'Attendance-Based Automatic Start')
        self.assertEqual(self.journey()['attendance_checkin'],'IN1')

    def test_replayed_confirmation_cannot_overwrite_live_route(self):
        self.checkin();self.confirm()
        points=[dict(latitude=12.,longitude=77.,timestamp=self.t0),
                dict(latitude=12.1,longitude=77.1,timestamp=self.t0+10000)]
        self.frappe.db.set_value('NetraNext Journey',self.journey()['name'],'raw_gps_data',json.dumps(points))
        self.confirm()
        self.assertEqual(json.loads(self.journey()['raw_gps_data']),points)

    def test_duplicate_checkin_keeps_original_anchor_and_pending_evidence(self):
        first=self.checkin()
        second=self.checkin('IN2')
        self.assertEqual(first['checkin_id'],second['checkin_id'])
        self.assertEqual(first['journey_id'],second['journey_id'])

    def test_empty_movement_confirmation_is_idempotent_and_never_delays_start(self):
        self.checkin()
        result=self.api.store_journey(dict(employee_id=self.employee,attendance_action='confirm',attendance_checkin='IN1',fixes=[]))
        self.assertEqual(result['status'],'success')
        self.assertEqual(len(self.store.get('NetraNext Journey')),1)

    def test_active_manual_and_scheduled_trips_are_not_overwritten(self):
        for source in ('manual','scheduled'):
            with self.subTest(source=source):
                self.store.tables['NetraNext Journey']=[]
                self.store.tables['Employee Checkin']=[]
                self.frappe.get_doc(dict(doctype='NetraNext Journey',name='EXISTING',journey_name='Existing trip',employee=self.employee,
                    flutter_journey_id='manual1',tracking_source=source,status='In Progress')).insert()
                context=self.checkin('IN'+source)
                self.assertIn('already in progress',context['start_error'])
                self.assertEqual(len(self.store.get('NetraNext Journey')),1)
                self.assertEqual(self.journey()['tracking_source'],source)
                self.assertEqual(self.journey()['status'],'In Progress')

    def test_dashboard_start_photo_updates_the_already_active_journey(self):
        self.checkin()
        result=self.api.store_journey(dict(employee_id=self.employee,attendance_action='start_photo',attendance_checkin='IN1',
            start_odometer=100,start_odometer_photo='image',start_odometer_source='manual'))
        self.assertEqual(result['status'],'success')
        self.assertFalse(self.context()['pending_start'])
        self.assertEqual(self.confirm()['status'],'success')
        self.assertEqual(self.journey()['start_odometer'],100.)

    def test_start_photo_during_trip_satisfies_requirement_on_same_journey(self):
        self.checkin()
        set_clock(datetime(2026,11,4,9,20))
        result=self.api.store_journey(dict(employee_id=self.employee,attendance_action='start_photo',attendance_checkin='IN1',
            start_odometer=999,start_odometer_photo='image',start_odometer_source='manual'))
        self.assertEqual(result['status'],'success')
        self.assertFalse(self.context()['pending_start'])
        self.assertEqual(self.journey()['start_odometer'],999)
        self.assertEqual(self.journey()['start_odometer_photo'],'/files/photo.jpg')
        self.assertEqual(len(self.store.get('NetraNext Journey')),1)
        self.assertNotIn('late_start_photo',self.context())

    def test_pending_start_photo_after_checkout_is_accepted_once(self):
        self.checkin()
        self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 18:00:00'),'OUT1')
        result=self.api.store_journey(dict(employee_id=self.employee,attendance_action='start_photo',attendance_checkin='IN1',
            start_odometer=999,start_odometer_photo='image',start_odometer_source='manual'))
        self.assertEqual(result['status'],'success')
        self.assertFalse(self.context()['pending_start'])
        self.assertTrue(self.context()['pending_end'])
        self.assertEqual(self.journey()['status'],'Completed')
        self.assertEqual(self.journey()['start_odometer'],999)
        again=self.api.store_journey(dict(employee_id=self.employee,attendance_action='start_photo',attendance_checkin='IN1',
            start_odometer=1000,start_odometer_photo='image',start_odometer_source='manual'))
        self.assertEqual(again['status'],'error')
        self.assertEqual(self.journey()['start_odometer'],999)

    def test_conflicting_trip_ending_never_backdates_an_attendance_start(self):
        self.frappe.get_doc(dict(doctype='NetraNext Journey',name='EXISTING',journey_name='Existing trip',employee=self.employee,
            flutter_journey_id='manual1',tracking_source='manual',status='In Progress')).insert()
        context=self.checkin()
        self.assertTrue(context['start_conflict'])
        self.assertIn('already in progress',context['start_error'])
        self.assertEqual(len(self.store.get('NetraNext Journey')),1)
        # Once the conflicting manual trip ends, a later state refresh must
        # not silently start a backdated automatic trip for this check-in.
        self.frappe.db.set_value('NetraNext Journey','EXISTING','status','Completed')
        set_clock(datetime(2026,11,4,9,10))
        response=self.api.store_journey(dict(employee_id=self.employee,attendance_action='state'))
        self.assertEqual(response['status'],'success')
        self.assertNotIn('started_at',self.context())
        self.assertEqual(len(self.store.get('NetraNext Journey')),1)

    def test_state_reconciles_a_checkout_whose_completion_write_failed(self):
        self.checkin();self.confirm()
        with patch.object(self.helper,'_write_journey',side_effect=RuntimeError('Save failure')):
            with self.assertRaises(RuntimeError):
                self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 10:00:00'),'OUT1')
        self.assertTrue(self.context()['closed'])
        self.assertEqual(self.journey()['status'],'In Progress')
        response=self.api.store_journey(dict(employee_id=self.employee,attendance_action='state'))
        self.assertEqual(response['status'],'success')
        self.assertEqual(self.journey()['status'],'Completed')
        self.assertTrue(self.context()['pending_end'])

    def test_start_reminder_claim_is_one_time_and_reports_the_receipt(self):
        self.checkin()
        result=self.claim_reminder()
        self.assertEqual(result['status'],'success')
        self.assertTrue(result['data']['claimed'])
        self.assertTrue(result['data']['context']['start_reminder_claimed'])
        self.assertEqual(self.context()['start_reminder']['claim_id'],'claim-1')
        replay=self.claim_reminder()
        self.assertEqual(replay['status'],'success')
        self.assertFalse(replay['data']['claimed'])
        self.assertTrue(replay['data']['suppressed'])
        self.assertTrue(self.context()['start_reminder']['claimed'])

    def test_start_reminder_claim_is_suppressed_once_photo_is_accepted(self):
        self.checkin()
        self.api.store_journey(dict(employee_id=self.employee,attendance_action='start_photo',attendance_checkin='IN1',
            start_odometer=100,start_odometer_photo='image',start_odometer_source='manual'))
        result=self.claim_reminder()
        self.assertEqual(result['status'],'success')
        self.assertFalse(result['data']['claimed'])
        self.assertTrue(result['data']['suppressed'])
        self.assertNotIn('start_reminder',self.context())

    def test_start_reminder_claim_rejects_unconfirmed_or_malformed_evidence(self):
        self.checkin()
        short=[dict(latitude=12.+20/111195,longitude=77.,accuracy=8,timestamp=self.t0+1000*t) for t in (1,2,3)]
        self.assertEqual(self.claim_reminder(fixes=short)['status'],'error')
        empty=self.claim_reminder(fixes=[])
        self.assertEqual(empty['status'],'error')
        self.assertIn('evidence',empty['message'])
        negative=self.claim_reminder(fixes=[dict(latitude=12.,longitude=77.,accuracy=-5,timestamp=self.t0+1000)])
        self.assertEqual(negative['status'],'error')
        self.assertNotIn('start_reminder',self.context())

    def test_start_reminder_claim_rejected_after_checkout(self):
        self.checkin()
        self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 10:00:00'),'OUT1')
        self.assertEqual(self.claim_reminder()['status'],'error')

    def test_stationary_checkin_does_not_need_accurate_movement_fixes(self):
        self.checkin()
        self.assertEqual(self.journey()['start_time'],'2026-11-04 09:00:00')
        set_clock(datetime(2026,11,4,9,10))
        response=self.api.store_journey(dict(employee_id=self.employee,attendance_action='state'))
        self.assertEqual(response['status'],'success')
        self.assertEqual(len(self.store.get('NetraNext Journey')),1)
        self.assertEqual(self.journey()['status'],'In Progress')

    def test_failed_start_retries_from_original_checkin_without_duplicate(self):
        with patch.object(self.helper,'_write_journey',side_effect=RuntimeError('Temporary failure')):
            context=self.checkin()
        self.assertIn('Temporary failure',context['start_error'])
        self.assertNotIn('started_at',self.context())
        set_clock(datetime(2026,11,4,9,10))
        response=self.api.store_journey(dict(employee_id=self.employee,attendance_action='state'))
        self.assertEqual(response['status'],'success')
        self.assertNotIn('start_error',response['data']['context'])
        self.assertEqual(self.journey()['start_time'],'2026-11-04 09:00:00')
        self.assertEqual(len(self.store.get('NetraNext Journey')),1)

    def test_photo_failure_keeps_dashboard_requirement_pending(self):
        self.checkin()
        with patch.object(self.helper,'_write_journey',side_effect=RuntimeError('Save failure')):
            response=self.api.store_journey(dict(employee_id=self.employee,attendance_action='start_photo',attendance_checkin='IN1',
                start_odometer=100,start_odometer_photo='image',start_odometer_source='manual'))
        self.assertEqual(response['status'],'error')
        self.assertTrue(self.context()['pending_start'])

    def test_manual_edit_setting_is_enforced(self):
        self.checkin();self.store.settings['allow_manual_odometer_edit']=0
        result=self.api.store_journey(dict(employee_id=self.employee,attendance_action='start_photo',attendance_checkin='IN1',
            start_odometer=100,start_odometer_photo='image',start_odometer_source='manual'))
        self.assertEqual(result['status'],'error')
        self.assertTrue(self.context()['pending_start'])

    def test_checkout_completes_same_journey_and_stale_sync_cannot_reopen(self):
        self.checkin();self.confirm()
        self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 10:00:00'),'OUT1')
        self.assertEqual(self.journey()['status'],'Completed')
        self.api.store_journey(dict(employee_id=self.employee,journey_id=self.context()['journey_id'],
            tracking_source='attendance_auto',attendance_checkin='IN1',status='In Progress'))
        self.assertEqual(self.journey()['status'],'Completed')
        self.assertTrue(self.context()['pending_end'])

    def test_checkout_does_not_end_manual_trip(self):
        self.checkin()
        self.frappe.get_doc(dict(doctype='NetraNext Journey',name='MANUAL',journey_name='Manual trip',employee=self.employee,
            flutter_journey_id='manual',status='In Progress')).insert()
        self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 10:00:00'),'OUT1')
        self.assertEqual(self.frappe.db.get_value('NetraNext Journey','MANUAL','status'),'In Progress')
        self.assertEqual(self.journey()['status'],'Completed')

    def test_employee_cannot_use_another_employees_checkin(self):
        self.checkin()
        result=self.api.store_journey(dict(employee_id='EMP2',attendance_action='start_photo',attendance_checkin='IN1',
            start_odometer=100,start_odometer_photo='image'))
        self.assertEqual(result['status'],'error')

    def test_end_photo_updates_existing_completed_journey_and_duplicate_checkout_keeps_it_satisfied(self):
        self.checkin();self.confirm()
        self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 10:00:00'),'OUT1')
        result=self.api.store_journey(dict(employee_id=self.employee,journey_id=self.context()['journey_id'],
            tracking_source='attendance_auto',attendance_checkin='IN1',status='Completed',
            end_odometer=150,end_odometer_photo='image',end_odometer_source='manual'))
        self.assertEqual(result['status'],'success')
        self.assertFalse(self.context()['pending_end'])
        self.assertEqual(self.context()['end_source'],'manual')
        self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 10:01:00'),'OUT2')
        self.assertFalse(self.context()['pending_end'])
        self.assertEqual(len(self.store.get('NetraNext Journey')),1)

    def test_invalid_manual_end_cannot_satisfy_pending_requirement(self):
        self.checkin();self.confirm()
        self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 10:00:00'),'OUT1')
        self.store.settings['allow_manual_odometer_edit']=0
        result=self.api.store_journey(dict(employee_id=self.employee,journey_id=self.context()['journey_id'],
            tracking_source='attendance_auto',attendance_checkin='IN1',status='Completed',
            end_odometer=150,end_odometer_photo='image',end_odometer_source='manual'))
        self.assertEqual(result['status'],'error')
        self.assertTrue(self.context()['pending_end'])

    def test_shared_movement_fixtures(self):
        from netranext_client.netranext.utils.movement_validation import evaluate_movement
        fixture=json.loads((HERE/'fixtures/movement_validation_cases.json').read_text())
        for case in fixture['cases']:
            with self.subTest(case=case['name']):
                self.assertEqual(evaluate_movement(case['anchor'],case['fixes'],now_ms=case.get('now_ms'))['status'],case['expect_status'])

    def test_manual_and_scheduled_use_unchanged_shared_store_path(self):
        for source in ('manual','scheduled'):
            with self.subTest(source=source):
                self.store.tables['NetraNext Journey']=[]
                if source=='scheduled':
                    self.frappe.get_doc(dict(doctype='Scheduled Trip',name='SCHED1',status='Scheduled')).insert()
                result=self.api.store_journey(dict(employee_id=self.employee,journey_id=source+'1',journey_name='Journey '+source,
                    tracking_source=source,trip_id='SCHED1' if source=='scheduled' else None,
                    start_time='2026-11-04 09:00:00',status='In Progress',raw_gps_data='[]'))
                self.assertEqual(result['status'],'success')
                self.assertEqual(self.journey()['flutter_journey_id'],source+'1')
                if source=='scheduled':
                    self.assertEqual(self.frappe.db.get_value('Scheduled Trip','SCHED1','status'),'In Progress')

    def test_migration_keeps_legacy_evidence_without_creating_trip_types(self):
        self.frappe.get_doc(dict(doctype='Employee Checkin',name='IN1',employee=self.employee,
            log_type='IN',time=datetime(2026,11,4,9))).insert()
        session=dict(name='OLD1',employee=self.employee,user_id='one@example.com',reserved_journey_id='auto-old',
            checkin_name='IN1',checkin_time=datetime(2026,11,4,9),checkin_latitude=12.,checkin_longitude=77.,
            status='monitoring',auto_start_snapshot=1,odometer_required=1)
        req=dict(kind='start',status='satisfied',evidence='PHOTO1')
        from _frappe_fake import AttrDict
        def sql(query,*args,**kwargs):
            if 'FROM `tabNetraNext Attendance Trip Session`' in query: return [AttrDict(session)]
            if 'FROM `tabNetraNext Trip Odometer Requirement`' in query: return [AttrDict(req)]
            if 'FROM `tabNetraNext Trip Odometer Evidence`' in query: return [AttrDict(photo_file='/private/files/old.jpg',reading_value=100,source='manual')]
            return []
        self.frappe.db.table_exists=lambda dt: True
        self.frappe.db.sql=sql
        custom=types.ModuleType('custom_fields');custom.create_custom_fields=MagicMock()
        with patch.dict(sys.modules,{'frappe.custom.doctype.custom_field.custom_field':custom}):
            migration=load('migration_under_test',ROOT/'patches/simplify_attendance_journeys.py')
            migration.execute()
            self.assertEqual(self.context()['start_source'],'manual')
            self.assertEqual(self.context()['start_photo'],'/private/files/old.jpg')
            self.assertFalse(self.context()['pending_start'])
            before=dict(self.context());migration.execute()
            self.assertEqual(self.context(),before)
            self.assertEqual(list(custom.create_custom_fields.call_args.args[0]),['Employee Checkin'])

    def test_delayed_checkout_does_not_close_a_new_checkin(self):
        self.checkin()
        self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 10:00:00'),'OUT1')
        self.frappe.get_doc(dict(doctype='Employee Checkin',name='IN2',employee=self.employee,
            log_type='IN',time=datetime(2026,11,4,11))).insert()
        self.helper.handle_checkin_stored(dict(employee_id=self.employee,latitude=12.,longitude=77.,tracking_accuracy=8),'IN2')
        self.assertIsNone(self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 10:00:00'),'OUT1'))
        self.assertFalse(self.helper.latest(self.employee,'IN2')[1]['closed'])

    def test_existing_trip_list_and_detail_include_live_route(self):
        self.checkin();self.confirm()
        response=self.api.get_journeys(employee_id=self.employee)
        self.assertEqual(response['status'],'success')
        journey=response['data']['journeys'][0]
        self.assertTrue(journey['isActive'])
        self.assertEqual(len(journey['points']),1)
        self.assertEqual(journey['reason'],'Attendance-Based Automatic Start')


    def test_original_miles_survive_attendance_context_and_trip_sync(self):
        self.checkin()
        result=self.api.store_journey(dict(employee_id=self.employee, attendance_action='start_photo',
            attendance_checkin='IN1', start_odometer=999, start_odometer_original=100,
            start_odometer_unit='mi', start_odometer_photo='image', start_odometer_source='detected'))
        self.assertEqual(result['status'],'success')
        self.assertEqual(self.context()['start_reading'],160.9344)
        self.assertEqual(self.context()['start_original'],100)
        self.assertEqual(self.context()['start_unit'],'mi')
        self.assertEqual(self.confirm()['status'],'success')
        self.assertEqual(self.journey()['start_odometer_original'],100)
        self.assertEqual(self.journey()['start_odometer_unit'],'mi')
        context=self.context()
        result=self.api.store_journey(dict(employee_id=self.employee, journey_id=context['journey_id'],
            tracking_source='attendance_auto', attendance_checkin='IN1', status='Completed',
            start_odometer=0, start_odometer_original=0, start_odometer_unit='km',
            end_odometer=0, end_odometer_original=110, end_odometer_unit='mi',
            end_odometer_photo='image',end_odometer_source='detected',distance_km=999))
        self.assertEqual(result['status'],'success')
        self.assertEqual(self.journey()['start_odometer_original'],100)
        self.assertEqual(self.journey()['end_odometer_original'],110)
        self.assertAlmostEqual(self.journey()['distance_km'],16.09344)
        self.assertAlmostEqual(self.journey()['calculated_odometer_distance'],16.09344)
        detail=self.api.get_journey_details(journey_id=context['journey_id'])['data']
        self.assertEqual(detail['startOdometerOriginal'],100)
        self.assertEqual(detail['startOdometerUnit'],'mi')
        self.assertEqual(detail['endOdometerOriginal'],110)
        self.assertEqual(detail['endOdometerUnit'],'mi')

    def test_unknown_unit_cannot_persist_attendance_evidence(self):
        self.checkin()
        result=self.api.store_journey(dict(employee_id=self.employee, attendance_action='start_photo',
            attendance_checkin='IN1', start_odometer_original=100, start_odometer_unit=None,
            start_odometer_photo='image', start_odometer_source='detected'))
        self.assertEqual(result['status'],'error')
        self.assertTrue(self.context()['pending_start'])

    def odometer_photo(self, phase, reading, **kwargs):
        request=dict(employee_id=self.employee, attendance_action=f'{phase}_photo', attendance_checkin='IN1',
            **{f'{phase}_odometer': reading, f'{phase}_odometer_photo': 'image',
               f'{phase}_odometer_source': 'detected'})
        request.update(kwargs)
        return self.api.store_journey(request)

    def test_end_photo_while_checked_in_links_to_live_trip_and_checkout_keeps_it(self):
        self.checkin()
        self.assertEqual(self.odometer_photo('start', 100)['status'],'success')
        result=self.odometer_photo('end', 150)
        self.assertEqual(result['status'],'success')
        state=result['data']['context']
        self.assertFalse(state['pending_end'])
        self.assertTrue(state['end_photo_received'])
        self.assertNotIn('end_photo',state)
        self.assertEqual(self.journey()['status'],'In Progress')
        self.assertEqual(self.journey()['end_odometer'],150)
        self.assertEqual(self.journey()['end_odometer_photo'],'/files/photo.jpg')
        self.assertEqual(self.journey()['calculated_odometer_distance'],50)
        # A live-trip heartbeat (or stale payload) never replaces the evidence.
        self.api.store_journey(dict(employee_id=self.employee, journey_id='attendance-IN1',
            tracking_source='attendance_auto', attendance_checkin='IN1', status='In Progress',
            end_odometer=999, end_odometer_photo='other', end_odometer_source='detected'))
        self.assertEqual(self.journey()['end_odometer'],150)
        self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 18:00:00'),'OUT1')
        self.assertEqual(self.journey()['status'],'Completed')
        self.assertEqual(self.journey()['end_odometer'],150)
        self.assertEqual(self.journey()['distance_km'],50)
        self.assertFalse(self.context()['pending_end'])

    def test_end_photo_needs_saved_start_photo_and_is_accepted_after_checkout(self):
        self.checkin()
        result=self.odometer_photo('end', 150)
        self.assertEqual(result['status'],'error')
        self.assertNotIn('end_photo_received',self.context())
        self.odometer_photo('start', 100)
        self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 18:00:00'),'OUT1')
        self.assertTrue(self.context()['pending_end'])
        result=self.odometer_photo('end', 150)
        self.assertEqual(result['status'],'success')
        self.assertTrue(self.context()['end_photo_received'])
        self.assertFalse(self.context()['pending_end'])

    def test_rejected_or_unsaved_end_photo_keeps_end_pending(self):
        self.checkin()
        self.odometer_photo('start', 100)
        self.assertEqual(self.odometer_photo('end', 90)['status'],'error')
        self.api._save_odometer_photo = lambda *a: None
        self.assertEqual(self.odometer_photo('end', 150)['status'],'error')
        self.assertNotIn('end_photo_received',self.context())
        self.assertIsNone(self.journey().get('end_odometer'))

    def test_end_photo_keeps_original_miles_with_canonical_km(self):
        self.checkin()
        self.odometer_photo('start', 999, start_odometer_original=100, start_odometer_unit='mi')
        result=self.odometer_photo('end', 0, end_odometer_original=110, end_odometer_unit='mi')
        self.assertEqual(result['status'],'success')
        self.assertAlmostEqual(self.context()['end_reading'],177.02784)
        self.assertEqual(self.journey()['end_odometer_original'],110)
        self.assertEqual(self.journey()['end_odometer_unit'],'mi')
        self.assertAlmostEqual(self.journey()['calculated_odometer_distance'],16.09344)

    def test_next_checkin_starts_a_fresh_odometer_flow(self):
        self.checkin()
        self.odometer_photo('start', 100)
        self.odometer_photo('end', 150)
        self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 18:00:00'),'OUT1')
        self.frappe.get_doc(dict(doctype='Employee Checkin',name='IN2',employee=self.employee,
            log_type='IN',time=datetime(2026,11,5,9))).insert()
        context=self.helper.handle_checkin_stored(dict(employee_id=self.employee,
            latitude=12.,longitude=77.,tracking_accuracy=8),'IN2')
        self.assertEqual(context['checkin_id'],'IN2')
        self.assertTrue(context['pending_start'])
        self.assertFalse(context['closed'])
        self.assertNotIn('end_photo_received',context)

    def record(self, name, log_type, when, **fields):
        self.frappe.get_doc(dict(doctype='Employee Checkin',name=name,employee=self.employee,
            log_type=log_type,time=when,**fields)).insert()

    def journey_named(self, flutter_id):
        return next(j for j in self.store.get('NetraNext Journey') if j['flutter_journey_id']==flutter_id)

    def test_odometer_disabled_trip_starts_and_ends_without_photos(self):
        self.store.settings['enable_odometer_reading']=0
        context=self.checkin()
        self.assertTrue(context['started_at'])
        self.assertFalse(context['odometer_required'])
        self.assertFalse(context['pending_start'])
        self.assertEqual(self.journey()['status'],'In Progress')
        closed=self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 18:00:00',
            latitude=12.1,longitude=77.1),'OUT1')
        self.assertTrue(closed['closed'])
        self.assertFalse(closed['pending_end'])
        self.assertEqual(self.journey()['status'],'Completed')
        self.assertEqual(self.journey()['end_location'],'12.1, 77.1')

    def test_disabled_tracking_never_starts_or_ends_any_journey(self):
        self.store.settings['enable_auto_attendance_trip_tracking']=0
        self.frappe.get_doc(dict(doctype='NetraNext Journey',name='MANUAL',journey_name='Manual trip',employee=self.employee,
            flutter_journey_id='manual',tracking_source='manual',status='In Progress')).insert()
        self.assertEqual(self.checkin(),{'skipped':'feature_disabled'})
        self.assertIsNone(self.helper.handle_checkout_stored(dict(employee_id=self.employee,
            time='2026-11-04 18:00:00'),'OUT1'))
        self.assertEqual([j['name'] for j in self.store.get('NetraNext Journey')],['MANUAL'])
        self.assertEqual(self.frappe.db.get_value('NetraNext Journey','MANUAL','status'),'In Progress')

    def test_state_closes_a_session_whose_checkout_the_hook_missed(self):
        self.checkin()
        # Check-out stored, but its trip hook never ran (failure before the
        # session was saved, or a check-out recorded outside the app).
        self.record('OUT1','OUT',datetime(2026,11,4,18),latitude=12.2,longitude=77.2)
        response=self.api.store_journey(dict(employee_id=self.employee,attendance_action='state'))
        self.assertEqual(response['status'],'success')
        session=response['data']['context']
        self.assertTrue(session['closed'])
        self.assertEqual(session['checkout_id'],'OUT1')
        self.assertTrue(session['pending_end'])
        self.assertEqual(self.journey()['status'],'Completed')
        self.assertEqual(self.journey()['end_time'],'2026-11-04 18:00:00')
        self.assertEqual(self.journey()['end_location'],'12.2, 77.2')
        # The closed session still accepts the evidence it is missing, once,
        # so the dashboard can finish the completed trip's odometer.
        self.assertEqual(self.odometer_photo('start',100)['status'],'success')
        self.assertEqual(self.odometer_photo('start',101)['status'],'error')

    def test_end_photo_after_checkout_finishes_pending_evidence_on_completed_journey(self):
        self.checkin()
        self.assertEqual(self.odometer_photo('start', 100)['status'],'success')
        self.record('OUT1','OUT',datetime(2026,11,4,18),latitude=12.2,longitude=77.2)
        closed=self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 18:00:00',
            latitude=12.2,longitude=77.2),'OUT1')
        self.assertTrue(closed['closed'])
        self.assertTrue(closed['pending_end'])
        self.assertEqual(self.journey()['status'],'Completed')
        # Below start is still rejected after check-out.
        self.assertEqual(self.odometer_photo('end', 90)['status'],'error')
        result=self.odometer_photo('end', 160)
        self.assertEqual(result['status'],'success')
        state=result['data']['context']
        self.assertFalse(state['pending_end'])
        self.assertTrue(state['closed'])
        journey=self.journey()
        self.assertEqual(journey['status'],'Completed')
        self.assertEqual(journey['end_time'],'2026-11-04 18:00:00')
        self.assertEqual(journey['end_odometer'],160)
        self.assertEqual(journey['end_odometer_photo'],'/files/photo.jpg')
        # Submitted end evidence is never replaced.
        self.assertEqual(self.odometer_photo('end', 170)['status'],'error')
        self.assertEqual(self.journey()['end_odometer'],160)

    def test_late_end_photo_after_checkout_still_requires_start_first(self):
        self.checkin()
        self.record('OUT1','OUT',datetime(2026,11,4,18))
        self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 18:00:00'),'OUT1')
        self.assertEqual(self.odometer_photo('end', 150)['status'],'error')
        self.assertEqual(self.odometer_photo('start', 100)['status'],'success')
        self.assertEqual(self.odometer_photo('end', 150)['status'],'success')
        self.assertEqual(self.journey()['start_odometer'],100)
        self.assertEqual(self.journey()['end_odometer'],150)

    def test_closed_session_without_odometer_requirement_accepts_no_photo(self):
        self.store.settings['enable_odometer_reading']=0
        self.checkin()
        self.record('OUT1','OUT',datetime(2026,11,4,18))
        closed=self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 18:00:00'),'OUT1')
        self.assertFalse(closed['pending_end'])
        self.assertEqual(self.odometer_photo('end', 150)['status'],'error')

    def test_missed_checkout_lets_the_next_checkin_start_its_own_trip(self):
        self.checkin()
        self.record('OUT1','OUT',datetime(2026,11,4,13))
        self.record('IN2','IN',datetime(2026,11,4,14))
        context=self.helper.handle_checkin_stored(dict(employee_id=self.employee,
            latitude=12.3,longitude=77.3,tracking_accuracy=8),'IN2')
        self.assertEqual(context['checkin_id'],'IN2')
        self.assertTrue(context['pending_start'])
        self.assertEqual(self.journey_named('attendance-IN1')['status'],'Completed')
        self.assertEqual(self.journey_named('attendance-IN1')['end_time'],'2026-11-04 13:00:00')
        self.assertEqual(self.journey_named('attendance-IN2')['status'],'In Progress')

    def test_next_day_checkin_supersedes_a_forgotten_checkout(self):
        self.checkin()
        last_fix='2026-11-04T17:30:00.000Z'
        self.frappe.db.set_value('NetraNext Journey',self.journey()['name'],'raw_gps_data',json.dumps([
            dict(latitude=12.,longitude=77.,timestamp=self.t0),
            dict(latitude=12.4,longitude=77.4,timestamp=last_fix)]))
        self.record('IN2','IN',datetime(2026,11,5,9))
        set_clock(datetime(2026,11,5,9))
        context=self.helper.handle_checkin_stored(dict(employee_id=self.employee,
            latitude=12.,longitude=77.,tracking_accuracy=8),'IN2')
        # A fresh trip and odometer flow for the new day...
        self.assertEqual(context['checkin_id'],'IN2')
        self.assertTrue(context['pending_start'])
        self.assertEqual(self.journey_named('attendance-IN2')['status'],'In Progress')
        # ...and yesterday's trip ends where tracking last saw the employee.
        old=self.helper.latest(self.employee,'IN1')[1]
        self.assertTrue(old['closed'])
        self.assertEqual(old['superseded_by'],'IN2')
        self.assertEqual(self.journey_named('attendance-IN1')['status'],'Completed')
        self.assertEqual(self.journey_named('attendance-IN1')['end_time'],'2026-11-04 17:30:00')
        self.assertEqual(self.journey_named('attendance-IN1')['end_location'],'12.4, 77.4')

    def test_forgotten_session_closes_even_when_tracking_was_turned_off(self):
        self.checkin()
        self.store.settings['enable_auto_attendance_trip_tracking']=0
        self.record('IN2','IN',datetime(2026,11,5,9))
        result=self.helper.handle_checkin_stored(dict(employee_id=self.employee,
            latitude=12.,longitude=77.,tracking_accuracy=8),'IN2')
        self.assertEqual(result,{'skipped':'feature_disabled'})
        self.assertTrue(self.helper.latest(self.employee,'IN1')[1]['closed'])
        self.assertEqual(self.journey()['status'],'Completed')
        self.assertEqual(len(self.store.get('NetraNext Journey')),1)

    def test_approved_next_day_checkin_is_not_blocked_by_a_forgotten_session(self):
        self.checkin()
        self.record('IN2','IN',datetime(2026,11,5,9),latitude=12.,longitude=77.,
            custom_location_status='Pending Approval')
        self.assertEqual(self.helper.handle_checkin_stored(dict(employee_id=self.employee,
            latitude=12.,longitude=77.,tracking_accuracy=8),'IN2'),{'skipped':'approval_pending'})
        self.frappe.db.set_value('Employee Checkin','IN2','custom_location_status','Approved')
        started=self.helper.start_after_approval('IN2')
        self.assertEqual(started['journey_id'],'attendance-IN2')
        self.assertTrue(started['started_at'])
        self.assertEqual(self.journey_named('attendance-IN1')['status'],'Completed')

if __name__ == '__main__':
    unittest.main()
