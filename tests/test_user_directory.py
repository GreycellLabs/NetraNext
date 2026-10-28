"""Versioned directory authentication, identity and query regressions (no live DB)."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class UserDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.frappe = MagicMock()
        self.frappe.whitelist = lambda **options: lambda fn: fn
        self.frappe.local.request = types.SimpleNamespace(method='POST')
        self.frappe.local.response = {}
        self.headers = {'X-NetraNext-Token': 'private-token', 'X-Tenant-ID': 'tenant-a'}
        self.frappe.get_request_header.side_effect = self.headers.get
        self.frappe.get_single.return_value.tenant_id = 'tenant-a'
        self.frappe.get_single.return_value.get_password.return_value = 'private-token'
        self.frappe.get_all.return_value = []
        modules = patch.dict(sys.modules, {'frappe': self.frappe})
        modules.start()
        self.addCleanup(modules.stop)
        path = Path(__file__).resolve().parents[1] / 'netranext_client/netranext/apis/v1/user_directory.py'
        spec = importlib.util.spec_from_file_location('directory_client_test', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_missing_token_and_missing_request_fail_closed(self):
        self.headers.clear()
        self.assertEqual(self.module.get_mobile_user_candidates()['error_code'], 'AUTHENTICATION_ERROR')
        self.frappe.local.request = None
        self.assertEqual(self.module.get_mobile_user_candidates()['error_code'], 'AUTHENTICATION_ERROR')
        self.frappe.get_all.assert_not_called()

    def test_wrong_token_cannot_read_directory(self):
        self.headers['X-NetraNext-Token'] = 'wrong-token'
        self.assertEqual(self.module.get_mobile_user_candidates()['error_code'], 'AUTHENTICATION_ERROR')
        self.assertEqual(self.frappe.local.response['http_status_code'], 401)
        self.frappe.get_all.assert_not_called()

    def test_wrong_or_missing_tenant_is_rejected(self):
        for value in ('tenant-b', ''):
            self.headers['X-Tenant-ID'] = value
            self.assertEqual(self.module.get_mobile_user_candidates()['error_code'], 'TENANT_IDENTITY_MISMATCH')
        self.frappe.get_all.assert_not_called()
        self.frappe.get_single.return_value.db_set.assert_not_called()

    def test_missing_configured_identity_requires_existing_handshake(self):
        self.frappe.get_single.return_value.tenant_id = ''
        self.assertEqual(self.module.get_mobile_user_candidates()['error_code'], 'TENANT_IDENTITY_NOT_CONFIGURED')
        self.frappe.get_all.assert_not_called()

    def test_query_pagination_and_versioned_response_use_only_user_table(self):
        self.frappe.get_all.return_value = [{'name': 'real-user@tenant-a', 'enabled': 1}]
        result = self.module.get_mobile_user_candidates(search='real-user', limit=10, offset=20)
        self.assertEqual(result['data']['tenant_id'], 'tenant-a')
        self.assertEqual(result['data']['protocol_version'], 1)
        self.assertEqual(result['data']['users'][0]['user'], 'real-user@tenant-a')
        call = self.frappe.get_all.call_args
        self.assertEqual(call.args, ('User',))
        self.assertEqual(call.kwargs['limit_start'], 20)
        self.assertEqual(call.kwargs['limit_page_length'], 10)
        self.assertEqual(call.kwargs['filters']['enabled'], 1)
        self.assertEqual(call.kwargs['filters']['name'], ['not in', ['Administrator', 'Guest']])
        self.frappe.get_all.assert_called_once()
        self.assertNotIn('private-token', str(result))

    def test_invalid_query_parameters_are_rejected_before_query(self):
        for limit, offset in [(0, 0), (201, 0), (20, -1), ('bad', 0), (None, None)]:
            self.assertEqual(self.module.get_mobile_user_candidates(limit=limit, offset=offset)['error_code'], 'VALIDATION_ERROR')
        self.assertEqual(self.module.get_mobile_user_candidates(search='x' * 321)['error_code'], 'VALIDATION_ERROR')
        self.frappe.get_all.assert_not_called()

    def test_query_errors_log_locations_without_sql_user_data_or_tokens(self):
        self.frappe.get_all.side_effect = RuntimeError('SQL private-user private-token')
        with self.assertLogs(self.module.logger, level='ERROR') as logs:
            result = self.module.get_mobile_user_candidates()
        self.assertEqual(result['error_code'], 'TENANT_DIRECTORY_QUERY_FAILED')
        self.assertEqual(len(result['reference']), 32)
        self.assertIn('RuntimeError', str(logs.output))
        self.assertIn('user_directory.py', str(logs.output))
        for secret in ('SQL', 'private-user', 'private-token'):
            self.assertNotIn(secret, str(logs.output))
            self.assertNotIn(secret, str(result))
        self.frappe.db.commit.assert_not_called()
