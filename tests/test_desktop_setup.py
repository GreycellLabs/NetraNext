"""Offline install/migrate regressions using a v16-shaped document store.

No database, user data, core schema modifications or live installation required.
"""
import copy
import importlib.util
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1] / 'netranext_client'


class Row(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    def __deepcopy__(self, memo):
        return type(self)({key: copy.deepcopy(value, memo) for key, value in self.items()})


def row(value):
    if isinstance(value, dict): return Row({k: row(v) for k, v in value.items()})
    if isinstance(value, list): return [row(v) for v in value]
    return value


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.store = {}
        self.inserted = []
        self.icon_fields = {'label', 'icon_type', 'link_type', 'link_to', 'bg_color', 'sidebar'}
        self.doc_types = {'Workspace Sidebar', 'Desktop Icon'}
        self.frappe = types.SimpleNamespace(
            flags=Row(in_import=False), conf=Row(developer_mode=0),
            cache=MagicMock(), clear_cache=MagicMock(), logger=MagicMock(),
            get_app_path=lambda *parts: str(ROOT.joinpath(*parts[1:])),
            get_meta=lambda kind: types.SimpleNamespace(has_field=lambda name: name in self.icon_fields),
            rename_doc=self.rename)
        self.frappe.db = types.SimpleNamespace(exists=self.exists, get_value=self.get_value)
        self.frappe.get_doc = self.get_doc
        self.patcher = patch.dict(sys.modules, {'frappe': self.frappe,
            'frappe.apps': types.SimpleNamespace(is_desk_apps=lambda apps: False)})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.setup = self.load('netranext/desktop_setup.py', 'desktop_under_test')
        self.module_patch = patch.dict(sys.modules, {'netranext_client.netranext.desktop_setup': self.setup})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.register = self.load('netranext/patches/register_pages.py', 'register_under_test')

    def load(self, path, name):
        spec = importlib.util.spec_from_file_location(name, ROOT / path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def get_value(self, kind, filters, field='name'):
        for (doctype, name), doc in self.store.items():
            if doctype == kind and all(doc.get(key) == value for key, value in filters.items()):
                return doc.get(field)
        return None

    def exists(self, kind, value):
        if kind == 'Role': return value in {'System Manager', 'HR Manager', 'HR User', 'Employee', 'All'}
        if kind == 'DocType': return value in self.doc_types
        if isinstance(value, dict): return self.get_value(kind, value)
        return value if (kind, value) in self.store else None

    def get_doc(self, kind, name=None):
        if isinstance(kind, str): return self.store[(kind, name)]
        data = row(copy.deepcopy(kind))
        data.setdefault('flags', Row())
        outer = self
        class Doc(Row):
            def insert(doc, **kwargs):
                doc_type = doc.doctype
                if doc_type == 'Workspace Sidebar':
                    assert doc.title, 'v16 sidebar autoname requires title'
                    doc.name = doc.title
                elif doc_type == 'Desktop Icon':
                    assert outer.exists(doc.link_type, doc.link_to), 'Dynamic Link must exist'
                    doc.name = doc.label
                elif doc_type == 'Page':
                    base = doc.page_name[:20]  # exercise old Page truncation repair
                    doc.name = base
                    counter = 1
                    while (doc_type, doc.name) in outer.store:
                        doc.name = f'{base}-{counter}'
                        counter += 1
                else:
                    doc.name = doc.get('name') or doc.get('title')
                key = (doc_type, doc.name)
                if key in outer.store:
                    assert kwargs.get('ignore_if_duplicate')
                    return outer.store[key]
                outer.store[key] = doc
                outer.inserted.append(key)
                return doc
            def append(doc, field, value):
                doc.setdefault(field, []).append(row(value))
        return Doc(data)

    def rename(self, kind, old, new, **kwargs):
        doc = self.store.pop((kind, old))
        doc.name = new
        self.store[(kind, new)] = doc

    def test_new_install_then_migrate_creates_one_correct_icon(self):
        self.assertEqual(self.register.execute()['status'], 'created')
        icon = self.store[('Desktop Icon', 'Netranext')]
        self.assertEqual({key: icon[key] for key in ('icon_type', 'link_type', 'link_to', 'idx', 'bg_color', 'hidden')},
                         dict(icon_type='Link', link_type='Workspace Sidebar', link_to='NetraNext',
                              idx=0, bg_color='gray', hidden=0))
        self.assertEqual(icon.standard, 1)
        self.assertEqual(icon.owner, 'Administrator')
        self.assertEqual(icon.sidebar, 'NetraNext')
        self.assertEqual(self.store[('Workspace Sidebar', 'NetraNext')].title, 'NetraNext')
        self.assertEqual(self.store[('Workspace Sidebar', 'NetraNext')]['items'][0]['link_to'], 'NetraNext')
        trip = next(item for item in self.store[('Workspace Sidebar', 'NetraNext')]['items']
                    if item.get('link_to') == 'netranext-trip-history')
        self.assertEqual(trip['child'], 1)
        before = len(self.inserted)
        self.assertEqual(self.register.execute()['status'], 'preserved')
        self.assertEqual(len(self.inserted), before)
        self.assertFalse(self.frappe.flags.in_import)
        self.assertEqual(self.frappe.conf.developer_mode, 0)

    def test_existing_customizations_and_roles_survive_migration(self):
        self.register.execute()
        workspace = self.store[('Workspace', 'NetraNext')]
        workspace.roles = [Row(role='HR Manager')]
        workspace.content = '[{"custom":"layout"}]'
        sidebar = self.store[('Workspace Sidebar', 'NetraNext')]
        sidebar.items = [Row(label='Custom', type='Link', link_type='Workspace', link_to='NetraNext')]
        icon = self.store.pop(('Desktop Icon', 'Netranext'))
        icon.update(name='My NetraNext', label='My NetraNext', bg_color='blue', idx=9, hidden=1,
                    roles=[Row(role='HR Manager')])
        self.store[('Desktop Icon', icon.name)] = icon
        expected = copy.deepcopy(self.store)
        self.assertEqual(self.register.execute()['icon'], 'My NetraNext')
        self.assertEqual(self.store, expected)

    def test_existing_workspace_without_icon_preserves_role_restrictions(self):
        self.register.execute()
        del self.store[('Desktop Icon', 'Netranext')]
        self.store[('Workspace', 'NetraNext')].roles = [Row(role='HR Manager')]
        result = self.setup.ensure_desktop_setup()
        self.assertEqual(result['status'], 'created')
        icon = self.store[('Desktop Icon', 'Netranext')]
        self.assertEqual(icon.roles, [{'role': 'HR Manager'}])
        self.assertNotIn('All', [r['role'] for r in icon.roles])

    def test_existing_target_sidebar_not_duplicated(self):
        self.register.execute()
        del self.store[('Desktop Icon', 'Netranext')]
        original = self.store[('Workspace Sidebar', 'NetraNext')]
        original.header_icon = 'custom-icon'
        self.setup.ensure_desktop_setup()
        self.assertIs(self.store[('Workspace Sidebar', 'NetraNext')], original)
        self.assertEqual(original.header_icon, 'custom-icon')

    def test_hidden_and_private_workspace_not_published(self):
        for attribute, value in [('is_hidden', 1), ('public', 0), ('for_user', 'owner@example.com')]:
            self.store.clear()
            self.setup.ensure_workspace()
            self.store[('Workspace', 'NetraNext')][attribute] = value
            self.assertEqual(self.setup.ensure_desktop_setup()['status'], 'preserved_private_or_hidden_workspace')
            self.assertFalse(any(kind == 'Desktop Icon' for kind, name in self.store))

    def test_conflicting_icon_name_not_overwritten_or_duplicated(self):
        self.store[('Desktop Icon', 'Netranext')] = Row(name='Netranext', link_type='External', link='https://example.com')
        result = self.register.execute()
        self.assertEqual(result['status'], 'name_conflict')
        self.assertEqual(self.store[('Desktop Icon', 'Netranext')].link, 'https://example.com')
        self.assertEqual(sum(kind == 'Desktop Icon' for kind, name in self.store), 1)

    def test_v15_does_not_receive_invalid_v16_records(self):
        self.doc_types.remove('Workspace Sidebar')
        self.assertEqual(self.register.execute()['status'], 'unsupported_desktop_schema')
        self.assertTrue(self.exists('Workspace', 'NetraNext'))
        self.assertFalse(any(kind in ('Desktop Icon', 'Workspace Sidebar') for kind, name in self.store))

    def test_retired_desktop_icon_schema_skips_without_crashing(self):
        # Evolving v16 builds keep Workspace Sidebar but retire Desktop Icon;
        # reading its meta must not fail installation, and the sidebar is
        # still created as navigation.
        self.doc_types.remove('Desktop Icon')
        self.assertEqual(self.register.execute()['status'], 'sidebar_only')
        self.assertTrue(self.exists('Workspace Sidebar', 'NetraNext'))
        self.assertFalse(any(kind == 'Desktop Icon' for kind, name in self.store))

    def test_early_v16_without_background_colour_still_gets_link(self):
        self.icon_fields.remove('bg_color')
        self.register.execute()
        self.assertEqual(self.store[('Desktop Icon', 'Netranext')].link_to, 'NetraNext')

    def test_import_context_restored_after_failed_insert(self):
        self.frappe.get_doc = MagicMock(side_effect=RuntimeError('DB unavailable'))
        with self.assertRaises(RuntimeError): self.setup._insert({'doctype': 'Desktop Icon'})
        self.assertFalse(self.frappe.flags.in_import)

    def test_existing_legacy_truncated_page_is_not_deleted(self):
        legacy = Row(name='netranext-expense-cl', title='Custom title', roles=[Row(role='HR Manager')])
        self.store[('Page', legacy.name)] = legacy
        self.register.execute()
        self.assertIs(self.store[('Page', legacy.name)], legacy)
        self.assertEqual(legacy.title, 'Custom title')
        self.assertTrue(self.exists('Page', 'netranext-expense-claims'))

    def test_page_creation_failure_restores_developer_mode(self):
        doc = types.SimpleNamespace(flags=Row(), append=MagicMock(),
                                    insert=MagicMock(side_effect=RuntimeError('Insert failed')))
        self.frappe.get_doc = lambda *args: doc
        with self.assertRaises(RuntimeError): self.register.execute()
        self.assertEqual(self.frappe.conf.developer_mode, 0)

    def test_install_and_migration_hooks_call_same_idempotent_setup(self):
        hooks = runpy.run_path(str(ROOT / 'hooks.py'))
        target = 'netranext_client.netranext.patches.register_pages.execute'
        self.assertEqual(hooks['after_install'], target)
        self.assertIn(target, hooks['after_migrate'])
