"""Exercise the real Journey validation boundary, independent of a database."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

class Document(dict):
    def __getattr__(self,name): return self.get(name)
    def __setattr__(self,name,value): self[name]=value
    def set(self,key,value): self[key]=value

class JourneyUnitBoundaryTests(unittest.TestCase):
    def setUp(self):
        frappe=types.ModuleType('frappe')
        def throw(message): raise ValueError(message)
        frappe.throw=throw
        document=types.ModuleType('frappe.model.document');document.Document=Document
        utils=types.ModuleType('frappe.utils');utils.strip_html=lambda value:value
        units=load('units',ROOT/'utils/odometer_units.py')
        self.patcher=patch.dict(sys.modules,{'frappe':frappe,'frappe.model.document':document,'frappe.utils':utils,
            'netranext_client.netranext.utils.odometer_units':units})
        self.patcher.start();self.addCleanup(self.patcher.stop)
        self.Journey=load('journey_unit_boundary',ROOT/'doctype/netranext_journey/netranext_journey.py').NetraNextJourney

    def test_original_miles_recomputes_trip_and_claim_distance_field(self):
        journey=self.Journey(start_odometer=999,end_odometer=999,distance_km=999,
            start_odometer_original=100,start_odometer_unit='mi',
            end_odometer_original=110,end_odometer_unit='mi')
        journey.validate_odometer_units()
        self.assertEqual(journey.start_odometer_original,100)
        self.assertEqual(journey.end_odometer_original,110)
        self.assertEqual(journey.start_odometer_unit,'mi')
        self.assertAlmostEqual(journey.start_odometer,160.9344)
        # create_expense_claim uses distance_km; GPS/client values cannot override this.
        self.assertAlmostEqual(journey.distance_km,16.09344)
        self.assertAlmostEqual(journey.total_distance,16.09344)
        self.assertAlmostEqual(journey.calculated_odometer_distance,16.09344)

    def test_zero_default_end_is_not_a_submitted_reading(self):
        journey=self.Journey(start_odometer=160.9344,end_odometer=0,
            start_odometer_original=100,start_odometer_unit='mi',
            end_odometer_original=0,end_odometer_unit='')
        journey.validate_odometer_units()
        self.assertNotIn('calculated_odometer_distance',journey)

    def test_zero_distance_is_valid_and_never_replaced_by_gps(self):
        journey=self.Journey(start_odometer_original=100,start_odometer_unit='mi',
            end_odometer_original=100,end_odometer_unit='mi',distance_km=99)
        journey.validate_odometer_units()
        self.assertEqual(journey.distance_km,0)

    def test_unknown_unit_and_below_start_fail_before_save(self):
        for fields in (dict(start_odometer_original=100,start_odometer_unit=''),
            dict(start_odometer_original=100,start_odometer_unit='mi',end_odometer_original=150,end_odometer_unit='km')):
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                self.Journey(**fields).validate_odometer_units()
