"""Trip authorization regressions with real policy/page code and mocked DB boundaries.

Run: python3 -m unittest discover -s tests -p test_trip_permissions.py
No database or production credentials required.
"""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1] / 'netranext_client'
POLICY = 'netranext_client.netranext.utils.trip_permissions'


class Denied(Exception):
    http_status_code = 403


class Row(dict):
    def __getattr__(self, key):
        return self.get(key)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TripPermissionTests(unittest.TestCase):
    def setUp(self):
        self.frappe = MagicMock()
        self.frappe.whitelist.side_effect = lambda **kw: lambda fn: fn
        self.frappe._ = lambda text: text
        self.frappe.PermissionError = Denied
        self.frappe.session.user = 'alice@example.com'
        self.frappe.throw.side_effect = lambda message, exc=Denied: (_ for _ in ()).throw(exc(message))
        self.roles = {'alice@example.com': ['Employee'], 'bob@example.com': ['Employee'],
                      'hr@example.com': ['Employee', 'HR Manager'], 'admin@example.com': ['System Manager']}
        self.employees = {'alice@example.com': ['EMP-A'], 'bob@example.com': ['EMP-B']}
        self.permission = True
        self.frappe.get_roles.side_effect = lambda user: self.roles.get(user, [])
        self.frappe.has_permission.side_effect = self.check_permission
        self.frappe.db.escape.side_effect = lambda text: "'" + text.replace("'", "''") + "'"
        self.frappe.db.exists.side_effect = self.exists
        self.frappe.db.get_value.side_effect = self.get_value
        self.frappe.get_all.side_effect = self.get_all
        self.frappe.get_list.return_value = []
        self.frappe.db.sql.return_value = []
        self.frappe.db.count.return_value = 0
        self.frappe.db.get_single_value.return_value = 2
        self.trips = {
            'TRIP-A': Row(name='TRIP-A', employee='EMP-A', status='Completed', distance_km=1,
                          start_time=None, end_time=None, metadata=None, raw_gps_data=None),
            'TRIP-B': Row(name='TRIP-B', employee='EMP-B', status='Completed', distance_km=2,
                          start_time=None, end_time=None, metadata=None, raw_gps_data=None),
        }
        self.frappe.get_doc.side_effect = lambda doctype, name: self.trips[name]
        query_module = types.ModuleType('frappe.model.db_query')
        self.query_constructor = MagicMock()
        self.query_constructor.return_value.execute.side_effect = lambda **kw: self.frappe.get_list('NetraNext Journey', **kw)
        query_module.DatabaseQuery = self.query_constructor
        self.modules = patch.dict(sys.modules, {'frappe': self.frappe, 'frappe.model.db_query': query_module})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.policy = load('trip_policy_test', ROOT / 'netranext/utils/trip_permissions.py')
        self.imports = patch.dict(sys.modules, {POLICY: self.policy})
        self.imports.start()
        self.addCleanup(self.imports.stop)
        self.page = load('trip_page_test', ROOT / 'netranext/page/netranext_trip_details/netranext_trip_details.py')
        self.dashboard = load('trip_dashboard_test', ROOT / 'netranext/apis/v1/dashboard.py')

    def check_permission(self, *args, **kwargs):
        if not self.permission and kwargs.get('throw'):
            raise Denied('Configured permissions deny access')
        return self.permission

    def exists(self, doctype, filters):
        if doctype == 'Employee' and isinstance(filters, dict):
            return filters['name'] in self.employees.get(filters.get('user_id'), [])
        if doctype == 'NetraNext Journey':
            return filters in self.trips
        return True

    def get_value(self, doctype, filters, field, **kwargs):
        if doctype == 'User':
            return 1 if filters in self.roles else 0
        if doctype == 'Employee' and isinstance(filters, dict):
            employees = self.employees.get(filters.get('user_id'), [])
            return employees[0] if employees else None
        if doctype == 'NetraNext Journey' and isinstance(filters, dict):
            return {'uuid-a': 'TRIP-A', 'uuid-b': 'TRIP-B'}.get(filters.get('flutter_journey_id'))
        return None

    def get_all(self, doctype, **kwargs):
        if doctype == 'Employee' and kwargs.get('pluck') == 'name':
            return self.employees.get(kwargs.get('filters', {}).get('user_id'), [])
        return []

    def test_standard_list_hook_uses_employee_user_mapping_not_creator(self):
        condition = self.policy.get_permission_query_conditions()
        self.assertIn('`tabNetraNext Journey`.`employee` IN', condition)
        self.assertIn("user_id = 'alice@example.com'", condition)
        self.assertNotIn('owner', condition)

    def test_hook_escapes_identity(self):
        self.assertIn("'alice'' OR 1=1 --'", self.policy.get_permission_query_conditions("alice' OR 1=1 --"))

    def test_standard_document_hook_vetoes_other_employee(self):
        self.assertIsNone(self.policy.has_permission(self.trips['TRIP-A']))
        self.assertFalse(self.policy.has_permission(self.trips['TRIP-B']))

    def test_extra_non_hr_role_does_not_grant_cross_employee_access(self):
        self.roles['alice@example.com'].append('Expense Approver')
        self.assertFalse(self.policy.has_permission(self.trips['TRIP-B']))

    def test_hr_admin_ownership_bypass_does_not_grant_permissions(self):
        for user in ('hr@example.com', 'admin@example.com', 'Administrator'):
            self.assertEqual(self.policy.get_permission_query_conditions(user), '')
            self.assertIsNone(self.policy.has_permission(self.trips['TRIP-B'], user))
        self.permission = False
        with self.assertRaises(Denied):
            self.policy.check_trip_read(self.trips['TRIP-B'], 'hr@example.com')

    def test_guest_has_no_query_or_document_access(self):
        self.assertEqual(self.policy.get_permission_query_conditions('Guest'), '1=0')
        self.assertFalse(self.policy.has_permission(self.trips['TRIP-A'], 'Guest'))
        self.frappe.session.user = 'Guest'
        with self.assertRaises(Denied):
            self.dashboard.get_dashboard_data()
        self.frappe.db.sql.assert_not_called()

    def test_missing_employee_mapping_cannot_fall_back_to_all_trips(self):
        self.frappe.session.user = 'unmapped@example.com'
        self.assertEqual(self.policy.scoped_filters(), [['name', '=', '']])
        with self.assertRaises(Denied):
            self.policy.check_trip_read(self.trips['TRIP-A'])

    def test_multiple_employee_records_for_same_login_are_supported(self):
        self.employees['alice@example.com'].append('EMP-A2')
        self.assertIn(['employee', 'in', ['EMP-A', 'EMP-A2']], self.policy.scoped_filters())

    def test_summary_employee_search_status_and_dates_cannot_remove_scope(self):
        self.page.get_all_trips_summary(employee='EMP-B', search='bob', status='Completed', date='2026-11-05')
        query = self.frappe.get_list.call_args
        self.assertEqual(query.args, ('NetraNext Journey',))
        self.assertIn(['employee', 'in', ['EMP-A']], query.kwargs['filters'])
        self.assertTrue(query.kwargs['or_filters'])
        self.assertNotIn('ignore_permissions', query.kwargs)

    def test_detail_denies_direct_name_and_flutter_id_before_telemetry(self):
        for trip_id in ('TRIP-B', 'uuid-b'):
            with self.assertRaises(Denied):
                self.page.get_trip_telemetry_details(trip_id)

    def test_own_detail_remains_available(self):
        detail = self.page.get_trip_telemetry_details('TRIP-A')
        self.assertEqual(detail['employee_id'], 'EMP-A')
        self.assertEqual(detail['trip_id'], 'TRIP-A')

    def test_hr_detail_remains_available_with_configured_read(self):
        self.frappe.session.user = 'hr@example.com'
        self.assertEqual(self.page.get_trip_telemetry_details('TRIP-B')['employee_id'], 'EMP-B')
        self.frappe.has_permission.assert_any_call('NetraNext Journey', 'read', doc=self.trips['TRIP-B'],
                                                 user='hr@example.com', throw=True)

    def test_history_uses_permission_query_and_and_scopes_spoofed_filters(self):
        result = self.dashboard.get_dashboard_data(ignore_dates=1, employee_id='EMP-B',
                                                   journey_employee='EMP-B', user_id='bob@example.com')
        self.assertEqual(result['status'], 'success')
        query = self.frappe.get_list.call_args
        self.assertIn(['employee', 'in', ['EMP-A']], query.kwargs['filters'])
        self.assertIn(['employee', '=', 'EMP-B'], query.kwargs['filters'])
        self.assertIn(['employee', 'in', ['EMP-B']], query.kwargs['filters'])
        for call in self.frappe.db.sql.call_args_list:
            self.assertNotIn('tabNetraNext Journey', call.args[0])

    def test_permission_denied_before_history_queries(self):
        self.permission = False
        with self.assertRaises(Denied):
            self.dashboard.get_dashboard_data()
        self.frappe.get_list.assert_not_called()

    def test_proxy_reader_rejects_missing_guest_and_disabled_users(self):
        for user in (None, '', 'Guest', 'disabled@example.com'):
            with self.assertRaises(Denied):
                self.policy.integration_reader(user)
        self.assertEqual(self.policy.integration_reader('alice@example.com'), 'alice@example.com')

    def load_sync(self):
        response = types.ModuleType('trip_response_test')
        response.create_success_response = lambda **kw: dict(status='success', **kw)
        response.create_error_response = lambda message, **kw: dict(status='error', message=message, **kw)
        errors = types.ModuleType('trip_errors_test')
        errors.handle_api_exception = lambda error, *args: dict(status='error',
            status_code=getattr(error, 'http_status_code', 400))
        for name in ('AuthenticationException', 'ValidationException', 'ResourceNotFoundException'):
            setattr(errors, name, type(name, (Exception,), {}))
        modules = patch.dict(sys.modules, {
            'frappe.utils': MagicMock(),
            'netranext_client.netranext.utils.response_formatter': response,
            'netranext_client.netranext.utils.logger': MagicMock(),
            'netranext_client.netranext.utils.error_handler': errors,
            'netranext_client.netranext.utils.validators': MagicMock(),
        })
        modules.start()
        self.addCleanup(modules.stop)
        sync = load('trip_sync_test', ROOT / 'netranext/apis/v1/sync.py')
        sync.real_validate_sync_request = sync.validate_sync_request
        sync.validate_sync_request = MagicMock()
        return sync

    def test_untrusted_request_cannot_supply_a_privileged_proxy_reader(self):
        sync = self.load_sync()
        sync.validate_sync_request = sync.real_validate_sync_request
        self.frappe.get_request_header.return_value = None
        result = sync.get_journey_details(trip_id='TRIP-B', requester_user='Administrator')
        self.assertEqual(result['status'], 'error')
        self.frappe.get_doc.assert_not_called()

    def test_mobile_flutter_id_is_authorized_like_document_name(self):
        sync = self.load_sync()
        self.frappe.get_meta.return_value.fields = [types.SimpleNamespace(fieldname='flutter_journey_id')]
        original = self.frappe.get_all.side_effect
        self.frappe.get_all.side_effect = lambda dt, **kw: [Row(name='TRIP-B')] if dt == 'NetraNext Journey' else original(dt, **kw)
        result = sync.get_journey_details(journey_id='uuid-b', requester_user='alice@example.com')
        self.assertEqual(result['status_code'], 403)
        self.assertNotIn('data', result)

    def test_mobile_detail_denies_foreign_trip_before_payload_serialization(self):
        sync = self.load_sync()
        result = sync.get_journey_details(trip_id='TRIP-B', requester_user='alice@example.com')
        self.assertEqual(result['status_code'], 403)
        self.assertNotIn('data', result)
        sync.validate_sync_request.assert_called_once()

    def test_mobile_own_detail_is_still_available(self):
        sync = self.load_sync()
        result = sync.get_journey_details(trip_id='TRIP-A', requester_user='alice@example.com')
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['data']['employee_id'], 'EMP-A')

    def test_mobile_list_rejects_spoofed_employee_and_user_filters(self):
        sync = self.load_sync()
        for filters in ({'employee_id': 'EMP-B'}, {'user_id': 'bob@example.com'}):
            result = sync.get_journeys(requester_user='alice@example.com', **filters)
            self.assertEqual(result['status_code'], 403)
        self.frappe.get_list.assert_not_called()

    def test_mobile_list_supplies_actor_to_permission_query(self):
        sync = self.load_sync()
        result = sync.get_journeys(requester_user='alice@example.com')
        self.assertEqual(result['status'], 'success')
        query = self.frappe.get_list.call_args
        self.assertEqual(query.kwargs['user'], 'alice@example.com')
        self.query_constructor.assert_called_once_with('NetraNext Journey', user='alice@example.com')
        self.assertIn(['employee', 'in', ['EMP-A']], query.kwargs['filters'])

    def test_mobile_delete_cannot_access_another_employee_trip(self):
        sync = self.load_sync()
        result = sync.delete_journey(trip_id='TRIP-B', requester_user='alice@example.com')
        self.assertEqual(result['status_code'], 403)
        self.frappe.delete_doc.assert_not_called()

    def test_mobile_extend_cannot_access_another_employee_trip(self):
        sync = self.load_sync()
        self.frappe.db.exists.side_effect = lambda dt, name: False if dt == 'Scheduled Trip' else self.exists(dt, name)
        result = sync.extend_trip(trip_id='TRIP-B', reason='reason', requester_user='alice@example.com')
        self.assertEqual(result['status_code'], 403)
        self.frappe.db.commit.assert_not_called()

    def test_mobile_permission_check_is_for_actor_not_integration_session(self):
        sync = self.load_sync()
        self.frappe.session.user = 'Administrator'
        result = sync.get_journey_details(trip_id='TRIP-B', requester_user='alice@example.com')
        self.assertEqual(result['status_code'], 403)

    def test_expense_trip_metadata_uses_visible_journeys(self):
        with patch.dict(sys.modules, {'frappe.utils': MagicMock()}):
            expense = load('trip_expense_test', ROOT / 'netranext/page/netranext_expense_claims/netranext_expense_claims.py')
        self.frappe.get_list.return_value = ['TRIP-A']
        expense.get_expense_claims()
        self.assertIn(['employee', 'in', ['EMP-A']], self.frappe.get_list.call_args.kwargs['filters'])
        sql = self.frappe.db.sql.call_args
        self.assertIn('j.name IN %s', sql.args[0])
        self.assertEqual(sql.args[1][0], ('TRIP-A',))

    def test_permission_error_response_contains_no_trip_payload(self):
        response = load('real_trip_response_test', ROOT / 'netranext/utils/response_formatter.py')
        with patch.dict(sys.modules, {
            'netranext_client.netranext.utils.response_formatter': response,
            'netranext_client.netranext.utils.logger': MagicMock(),
        }):
            errors = load('real_trip_error_test', ROOT / 'netranext/utils/error_handler.py')
        result = errors.handle_api_exception(Denied('TRIP-B private route'))
        self.assertEqual(result['status_code'], 403)
        self.assertEqual(result['error_code'], 'PERMISSION_DENIED')
        self.assertNotIn('TRIP-B', str(result))
        self.assertNotIn('data', result)

    def test_service_bench_local_policy_matches_client_ownership_policy(self):
        service_root = ROOT.parents[3] / 'NetraNext-Service/apps/netranext/netranext'
        service_policy = load('service_trip_policy_test', service_root / 'utils/trip_permissions.py')
        for user in ('alice@example.com', 'Guest', 'hr@example.com', 'Administrator'):
            self.assertEqual(service_policy.get_permission_query_conditions(user),
                             self.policy.get_permission_query_conditions(user))
        self.assertFalse(service_policy.has_permission(self.trips['TRIP-B'], 'alice@example.com'))

    def test_legacy_service_dashboards_reject_guest_before_any_queries(self):
        service_root = ROOT.parents[3] / 'NetraNext-Service/apps/netranext/netranext'
        service_policy = load('service_trip_policy_test', service_root / 'utils/trip_permissions.py')
        self.frappe.session.user = 'Guest'
        modules = {'netranext.utils.trip_permissions': service_policy,
                   'netranext.utils.response_formatter': MagicMock(),
                   'netranext.utils.logger': MagicMock(),
                   'netranext.utils.error_handler': MagicMock(),
                   'netranext.utils.auth_helper': MagicMock()}
        with patch.dict(sys.modules, modules):
            for filename, method in (('dashboard', 'get_dashboard_data'),
                                     ('dashboard_real', 'get_dashboard_data_real'),
                                     ('dashboard_working', 'get_dashboard_data_real')):
                dashboard = load('legacy_' + filename, service_root / ('apis/v1/' + filename + '.py'))
                with self.assertRaises(Denied):
                    getattr(dashboard, method)()
        self.frappe.db.sql.assert_not_called()
        self.frappe.get_list.assert_not_called()

    def test_hooks_are_registered_for_standard_rest_list_export_and_document_reads(self):
        apps = types.ModuleType('frappe.apps')
        apps.is_desk_apps = lambda apps: False
        with patch.dict(sys.modules, {'frappe.apps': apps}):
            hooks = load('trip_hooks_test', ROOT / 'hooks.py')
        self.assertEqual(hooks.permission_query_conditions['NetraNext Journey'], POLICY + '.get_permission_query_conditions')
        self.assertEqual(hooks.has_permission['NetraNext Journey'], POLICY + '.has_permission')


if __name__ == '__main__':
    unittest.main()
