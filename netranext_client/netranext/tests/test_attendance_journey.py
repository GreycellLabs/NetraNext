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
        for name, file in [('response_formatter','utils/response_formatter.py'),('movement_validation','utils/movement_validation.py')]:
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

    def context(self):
        return self.helper.latest(self.employee,'IN1')[1]

    def journey(self):
        return self.store.get('NetraNext Journey')[0]

    def test_checkin_only_arms_without_creating_a_trip(self):
        context=self.checkin()
        self.assertTrue(context['pending_start'])
        self.assertEqual(context['checkin_id'],'IN1')
        self.assertEqual(self.store.get('NetraNext Journey'),[])

    def test_disabled_setting_changes_nothing(self):
        self.store.settings['enable_auto_attendance_trip_tracking']=0
        self.assertIsNone(self.checkin())
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

    def test_invalid_movement_cannot_start(self):
        self.checkin()
        result=self.api.store_journey(dict(employee_id=self.employee,attendance_action='confirm',attendance_checkin='IN1',fixes=[]))
        self.assertEqual(result['status'],'error')
        self.assertEqual(self.store.get('NetraNext Journey'),[])

    def test_active_manual_and_scheduled_trips_are_not_overwritten(self):
        for source in ('manual','scheduled'):
            with self.subTest(source=source):
                self.store.tables['NetraNext Journey']=[]
                self.checkin('IN'+source)
                self.frappe.get_doc(dict(doctype='NetraNext Journey',name='EXISTING',employee=self.employee,
                    flutter_journey_id='manual1',tracking_source=source,status='In Progress')).insert()
                result=self.api.store_journey(dict(employee_id=self.employee,attendance_action='confirm',
                    attendance_checkin='IN'+source,fixes=[]))
                self.assertEqual(result['status'],'error')
                self.assertEqual(self.journey()['status'],'In Progress')

    def test_start_photo_is_deferred_and_predeparture_reading_is_reused(self):
        self.checkin()
        result=self.api.store_journey(dict(employee_id=self.employee,attendance_action='start_photo',attendance_checkin='IN1',
            start_odometer=100,start_odometer_photo='image',start_odometer_source='manual'))
        self.assertEqual(result['status'],'success')
        self.assertFalse(self.context()['pending_start'])
        self.assertEqual(self.confirm()['status'],'success')
        self.assertEqual(self.journey()['start_odometer'],100.)

    def test_late_start_photo_stays_pending_and_does_not_populate_start(self):
        self.checkin();self.confirm()
        result=self.api.store_journey(dict(employee_id=self.employee,attendance_action='start_photo',attendance_checkin='IN1',
            start_odometer=999,start_odometer_photo='late',start_odometer_source='manual'))
        self.assertEqual(result['status'],'success')
        self.assertTrue(self.context()['pending_start'])
        self.assertIsNone(self.journey().get('start_odometer'))
        self.assertEqual(self.context()['late_start_photo'],'/files/photo.jpg')

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
        self.frappe.get_doc(dict(doctype='NetraNext Journey',name='MANUAL',employee=self.employee,
            flutter_journey_id='manual',status='In Progress')).insert()
        self.helper.handle_checkout_stored(dict(employee_id=self.employee,time='2026-11-04 10:00:00'),'OUT1')
        self.assertEqual(self.journey()['status'],'In Progress')

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
                result=self.api.store_journey(dict(employee_id=self.employee,journey_id=source+'1',
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


if __name__ == '__main__':
    unittest.main()
