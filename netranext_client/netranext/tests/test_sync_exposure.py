"""HTTP exposure contract of the tenant sync API, read from the real source.

The in-memory Frappe fakes used by the behaviour tests turn
`@frappe.whitelist` into a no-op, so they cannot notice a missing or
misplaced decorator. That is exactly how `store_journey` once lost its
whitelist (a helper inserted between the decorator and the function): every
hub -> tenant journey sync, manual and attendance alike, got HTTP 403.

Run: python3 -m unittest discover -s netranext/tests -p test_sync_exposure.py
"""
import ast
import re
import unittest
from pathlib import Path

SYNC = Path(__file__).resolve().parents[1] / 'apis' / 'v1' / 'sync.py'
HUB = Path(__file__).resolve().parents[4] / 'NetraNext-service' / 'netranext'

# Sync endpoints the hub must be able to call over HTTP.
REQUIRED = {
    'store_attendance', 'store_journey', 'get_journeys', 'get_journey_details',
    'update_scheduled_trip_status', 'extend_trip', 'delete_journey', 'get_employee_data',
}
# Deliberately reachable without the X-NetraNext-Token check: a public
# liveness probe, and the user directory, which authenticates on its own.
UNAUTHENTICATED_BY_DESIGN = {'health_check', 'get_mobile_user_candidates'}


def _functions():
    tree = ast.parse(SYNC.read_text())
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _whitelisted(node):
    return any('whitelist' in ast.unparse(d) for d in node.decorator_list)


def _calls(node, name):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
               for n in ast.walk(node))


class SyncExposureTests(unittest.TestCase):
    def setUp(self):
        self.functions = _functions()
        self.exposed = {name for name, node in self.functions.items() if _whitelisted(node)}

    def test_hub_endpoints_are_whitelisted(self):
        missing = sorted(REQUIRED - self.exposed)
        self.assertEqual(missing, [], f'not whitelisted (Frappe answers 403): {missing}')

    def test_private_helpers_are_never_exposed(self):
        exposed_private = sorted(n for n in self.exposed if n.startswith('_'))
        self.assertEqual(exposed_private, [])

    def test_exposed_endpoints_check_the_integration_token(self):
        unchecked = sorted(n for n in self.exposed - UNAUTHENTICATED_BY_DESIGN
                           if not _calls(self.functions[n], 'validate_sync_request'))
        self.assertEqual(unchecked, [], f'whitelisted without X-NetraNext-Token check: {unchecked}')

    def test_every_sync_method_the_hub_calls_and_exists_is_whitelisted(self):
        if not HUB.is_dir():
            self.skipTest('NetraNext-service checkout not found next to this repo')
        called = set()
        for path in HUB.rglob('*.py'):
            called |= set(re.findall(r'netranext_client\.netranext\.apis\.v1\.sync\.(\w+)',
                                     path.read_text(errors='ignore')))
        existing = called & set(self.functions)
        self.assertEqual(sorted(existing - self.exposed), [])


if __name__ == '__main__':
    unittest.main()
