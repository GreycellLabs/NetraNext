"""Legacy data repair and native Frappe landing-path regressions; no live DB."""
import copy
import importlib.util
import json
from pathlib import Path
import runpy
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1] / 'netranext_client'
try:
    import frappe.apps as native_apps
    import frappe.auth as native_auth
except ImportError:
    native_apps = native_auth = None


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.rows = [
            {'name': 'Administrator', 'user_type': 'System User', 'default_workspace': 'NetraNext', 'roles': ['System Manager']},
            {'name': 'employee', 'user_type': 'System User', 'default_workspace': 'NetraNext', 'roles': ['Employee']},
            {'name': 'hr', 'user_type': 'System User', 'default_workspace': 'Home', 'roles': ['HR Manager']},
            {'name': 'new', 'user_type': 'System User', 'default_workspace': None, 'roles': []},
            {'name': 'portal', 'user_type': 'Website User', 'default_workspace': 'NetraNext', 'roles': []}]
        self.frappe = MagicMock()
        self.frappe.get_site_path.return_value = self.directory.name
        self.frappe.db.sql.side_effect = lambda *args, **kwargs: [
            {'name': row['name'], 'default_workspace': row['default_workspace']}
            for row in self.rows if row['user_type'] == 'System User' and row['default_workspace'] == 'NetraNext']
        self.frappe.db.set_value.side_effect = self.set_value
        modules = patch.dict(sys.modules, {'frappe': self.frappe,
            'frappe.apps': types.SimpleNamespace(is_desk_apps=lambda apps: False)})
        modules.start()
        self.addCleanup(modules.stop)
        spec = importlib.util.spec_from_file_location('repair_web_defaults', ROOT / 'netranext/patches/clear_legacy_netranext_default_workspace.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def set_value(self, doctype, name, field, value, **kwargs):
        self.assertTrue(list(Path(self.directory.name).glob('*.json')), 'Backup must precede any update')
        self.assertEqual((doctype, field, kwargs), ('User', 'default_workspace', {'update_modified': False}))
        next(row for row in self.rows if row['name'] == name)[field] = value

    def test_only_matching_system_user_preferences_are_repaired_after_private_backup(self):
        previous = copy.deepcopy(self.rows)
        self.module.execute()
        archive = next(Path(self.directory.name).glob('*.json'))
        data = json.loads(archive.read_text())
        self.assertEqual({row['name'] for row in data['rows']}, {'Administrator', 'employee'})
        self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
        self.assertEqual(self.rows[0]['default_workspace'], None)
        self.assertEqual(self.rows[1]['default_workspace'], None)
        self.assertEqual(self.rows[2:], previous[2:])
        self.assertEqual([r['roles'] for r in self.rows], [r['roles'] for r in previous])
        self.frappe.db.commit.assert_not_called()
        self.frappe.clear_cache.assert_any_call(user='Administrator')
        self.frappe.clear_cache.assert_any_call(user='employee')
        query = self.frappe.db.sql.call_args
        self.assertIn('for update', query.args[0])
        self.assertEqual(query.args[1], ('System User', 'NetraNext', 'Guest'))

    def test_no_targets_is_a_noop_and_rerun_does_not_create_another_backup(self):
        self.module.execute()
        self.frappe.db.set_value.reset_mock()
        self.module.execute()
        self.frappe.db.set_value.assert_not_called()
        self.assertEqual(len(list(Path(self.directory.name).glob('*.json'))), 1)

    def test_backup_failure_aborts_without_changing_preferences(self):
        original = copy.deepcopy(self.rows)
        with patch.object(self.module.os, 'fsync', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.module.execute()
        self.assertEqual(self.rows, original)
        self.frappe.db.set_value.assert_not_called()
        self.frappe.clear_cache.assert_not_called()

    def test_corrupt_backup_is_rejected_before_changes(self):
        with patch.object(Path, 'read_bytes', return_value=b'corrupt'):
            with self.assertRaises(RuntimeError):
                self.module.execute()
        self.frappe.db.set_value.assert_not_called()

    def test_one_time_patch_is_registered_and_no_login_redirect_hook_is_added(self):
        hooks = runpy.run_path(str(ROOT / 'hooks.py'))
        self.assertEqual(hooks['add_to_apps_screen'][0]['route'], '/app')
        for key in ('home_page', 'role_home_page', 'get_website_user_home_page', 'on_login'):
            self.assertNotIn(key, hooks)
        target = 'netranext_client.netranext.patches.clear_legacy_netranext_default_workspace'
        self.assertEqual((ROOT / 'patches.txt').read_text().splitlines().count(target), 1)
        self.assertNotIn(target, hooks['after_migrate'])


    def test_newer_framework_desk_route_uses_native_classifier(self):
        with patch.dict(sys.modules, {'frappe.apps': types.SimpleNamespace(is_desk_apps=lambda apps: True)}):
            hooks = runpy.run_path(str(ROOT / 'hooks.py'))
        self.assertEqual(hooks['add_to_apps_screen'][0]['route'], '/desk')

    def test_launcher_remains_available_to_desk_users_but_not_portal_or_guest(self):
        spec = importlib.util.spec_from_file_location('app_boot_under_test', ROOT / 'netranext/boot.py')
        boot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(boot)
        for user, kind, allowed in [('Administrator', 'System User', True),
                                    ('employee', 'System User', True),
                                    ('portal', 'Website User', False), ('Guest', 'Website User', False)]:
            self.frappe.session.user = user
            self.frappe.get_cached_value.return_value = kind
            self.assertEqual(boot.has_app_permission(), allowed)
        self.frappe.db.set_value.assert_not_called()



@unittest.skipIf(native_apps is None, 'Run with the bench Python environment for native Frappe tests')
class NativeLandingTests(unittest.TestCase):
    def setUp(self):
        self.hooks = runpy.run_path(str(ROOT / 'hooks.py'))
        self.frappe = MagicMock()
        self.response = {}
        self.frappe.local.response = self.frappe.response = self.response
        self.frappe.cache.hget.return_value = None
        self.frappe.get_system_settings.return_value = None
        self.frappe.db.get_value.return_value = None
        self.apps = [{'name': 'netranext_client', 'route': self.hooks['add_to_apps_screen'][0]['route']}]
        for target, name, value in [(native_apps, 'frappe', self.frappe),
                                    (native_auth, 'frappe', self.frappe),
                                    (native_apps, 'get_apps', lambda: self.apps)]:
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def login_response(self, user='normal', workspace=None, user_type='System User'):
        self.response.clear()
        manager = native_auth.LoginManager.__new__(native_auth.LoginManager)
        manager.user = user
        manager.info = types.SimpleNamespace(user_type=user_type, first_name='Test', last_name='User',
            user_image='', default_workspace=workspace)
        manager.set_user_info()
        return dict(self.response)

    def test_old_app_route_reproduces_implicit_redirect_and_new_route_returns_desk(self):
        self.apps[0]['route'] = '/app/netranext'
        self.assertEqual(native_apps.get_default_path(), '/app/netranext')
        self.apps[0]['route'] = self.hooks['add_to_apps_screen'][0]['route']
        self.assertEqual(native_apps.get_default_path(), '/app')

    def test_administrator_and_system_users_with_various_roles_use_normal_desk(self):
        for user, roles in [('Administrator', ['System Manager']), ('employee', ['Employee']),
                            ('hr', ['HR Manager']), ('new-user', ['All'])]:
            self.frappe.get_roles.return_value = roles
            self.assertEqual(self.login_response(user)['home_page'], '/app')
            self.assertEqual(self.response['message'], 'Logged In')

    def test_persisted_legacy_preference_explains_old_behavior_then_native_clear_fixes_it(self):
        self.assertEqual(self.login_response(workspace='NetraNext')['home_page'], '/app/netranext')
        self.assertEqual(self.login_response(workspace=None)['home_page'], '/app')

    def test_other_saved_workspaces_and_future_explicit_preferences_are_native(self):
        self.assertEqual(self.login_response(workspace='Accounting')['home_page'], '/app/accounting')
        self.assertEqual(self.login_response(workspace='NetraNext')['home_page'], '/app/netranext')

    def test_user_and_system_default_apps_are_not_replaced(self):
        self.apps += [{'name': 'erpnext', 'route': '/app/home'}, {'name': 'hrms', 'route': '/app/hr'}]
        self.frappe.get_system_settings.return_value = 'hrms'
        self.assertEqual(self.login_response()['home_page'], '/app/hr')
        self.frappe.db.get_value.return_value = 'erpnext'
        self.assertEqual(self.login_response()['home_page'], '/app/home')
        self.frappe.db.get_value.return_value = 'netranext_client'
        self.assertEqual(self.login_response()['home_page'], '/app')

    def test_website_user_portal_and_cached_redirect_are_not_overridden(self):
        with patch.object(native_auth, 'get_default_path', return_value=None), \
             patch.object(native_auth, 'get_home_page', return_value='me'):
            result = self.login_response(user_type='Website User')
        self.assertEqual(result['message'], 'No App')
        self.assertEqual(result['home_page'], '/me')
        self.frappe.local.cookie_manager.set_cookie.assert_any_call('system_user', 'no')
        self.frappe.cache.hget.return_value = '/app/netranext'
        self.assertEqual(self.login_response()['redirect_to'], '/app/netranext')

    def test_repeated_login_without_app_forcing_uses_same_native_result(self):
        self.assertEqual(self.login_response()['home_page'], '/app')
        self.assertEqual(self.login_response()['home_page'], '/app')
