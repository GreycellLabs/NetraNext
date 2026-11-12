"""NetraNext Settings > Allow Manual Odometer Reading Edit, enforced server-side.

Offline: frappe and sibling modules are stubbed, the real modules are loaded by
file path. The hub downgrades a "detected" source without a valid OCR proof to
"manual" (NetraNext-service tests/test_odometer_proof.py); these tests pin the
tenant half: only "detected" passes with edits disabled, and the read-only
exception flow ("unreadable": photo without a reading) is accepted.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PACKAGE = Path(__file__).resolve().parents[1] / "netranext_client/netranext"


class Thrown(Exception):
	pass


class ValidationException(Exception):
	pass


def load(name, path):
	spec = importlib.util.spec_from_file_location(name, path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


class EditEnforcementTests(unittest.TestCase):
	def setUp(self):
		self.frappe = MagicMock()
		self.frappe.whitelist.side_effect = lambda **kwargs: (lambda fn: fn)
		self.frappe.throw.side_effect = Thrown
		self.settings = types.SimpleNamespace(allow_manual_odometer_edit=0)
		self.frappe.get_single.return_value = self.settings
		errors = types.SimpleNamespace(handle_api_exception=MagicMock(), AuthenticationException=Exception,
									   ValidationException=ValidationException, ResourceNotFoundException=Exception)
		modules = {
			"frappe": self.frappe, "frappe.utils": MagicMock(), "pytz": MagicMock(),
			"netranext_client": types.ModuleType("netranext_client"),
			"netranext_client.netranext": types.ModuleType("netranext_client.netranext"),
			"netranext_client.netranext.utils": types.ModuleType("netranext_client.netranext.utils"),
			"netranext_client.netranext.utils.response_formatter": MagicMock(),
			"netranext_client.netranext.utils.logger": MagicMock(),
			"netranext_client.netranext.utils.error_handler": errors,
			"netranext_client.netranext.utils.validators": MagicMock(),
		}
		self.modules = patch.dict(sys.modules, modules)
		self.modules.start()
		self.addCleanup(self.modules.stop)
		self.sync = load("sync_under_test", PACKAGE / "apis/v1/sync.py")
		self.journey = load("attendance_journey_under_test", PACKAGE / "utils/attendance_journey.py")

	def validate(self, **data):
		return self.sync._validate_odometer_sources(data)

	def test_edits_disabled_only_detected_readings_pass(self):
		self.validate(start_odometer=100.0, start_odometer_source="detected")
		with self.assertRaises(ValidationException):
			self.validate(start_odometer=100.0, start_odometer_source="manual")
		with self.assertRaises(ValidationException):
			self.validate(end_odometer=100.0)  # old app, no source marker
		with self.assertRaises(ValidationException):
			self.validate(end_odometer=100.0, end_odometer_source="unreadable")

	def test_edits_enabled_accepts_manual(self):
		self.settings.allow_manual_odometer_edit = 1
		self.validate(start_odometer=100.0, start_odometer_source="manual")

	def test_unreadable_exception_has_no_reading_to_validate(self):
		self.validate(start_odometer=None, start_odometer_source="unreadable", start_odometer_photo="x")

	def test_attendance_photo_reading_rules(self):
		reading = self.journey._photo_reading
		self.assertEqual(reading(dict(start_odometer=12.5, start_odometer_photo="p"), "start"), 12.5)
		self.assertIsNone(reading(dict(end_odometer_photo="p", end_odometer_source="unreadable"), "end"))
		with self.assertRaises(Thrown):
			reading(dict(start_odometer_photo="p", start_odometer_source="manual"), "start")
		with self.assertRaises(Thrown):
			reading(dict(start_odometer=10, start_odometer_source="unreadable"), "start")  # photo required
		with self.assertRaises(Thrown):
			reading(dict(start_odometer=-1, start_odometer_photo="p"), "start")


if __name__ == "__main__":
	unittest.main()
