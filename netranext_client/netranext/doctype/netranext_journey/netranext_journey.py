import frappe
from frappe.model.document import Document
import json


class NetraNextJourney(Document):
	def validate(self):
		"""Validate journey data"""
		self.validate_employee()
		self.validate_gps_data()

	def validate_employee(self):
		"""Validate employee exists and is active"""
		if not self.employee:
			frappe.throw("Employee is required")

		employee = frappe.get_doc("Employee", self.employee)
		if employee.status != "Active":
			frappe.throw("Cannot create journey for inactive employee")

	def validate_gps_data(self):
		"""Validate GPS data if present"""
		if self.raw_gps_data:
			try:
				gps_data = json.loads(self.raw_gps_data)
				if not isinstance(gps_data, list):
					frappe.throw("Raw GPS data must be a valid JSON array")
			except json.JSONDecodeError:
				frappe.throw("Invalid JSON format in Raw GPS Data")

	def before_save(self):
		"""Process journey data before saving"""
		self.calculate_journey_stats()

	def calculate_journey_stats(self):
		"""Calculate journey statistics if GPS data available"""
		if self.raw_gps_data and not self.distance_km:
			try:
				gps_data = json.loads(self.raw_gps_data)
				if gps_data and len(gps_data) > 1:
					# Calculate distance (simplified - should use proper GPS distance calculation)
					self.distance_km = self._calculate_distance(gps_data)
					self.original_points_count = len(gps_data)
			except (json.JSONDecodeError, AttributeError):
				pass

	def _calculate_distance(self, gps_points):
		"""Calculate total distance from GPS points (simplified)"""
		# This should be replaced with proper Haversine formula calculation
		# For now, return 0 as placeholder
		return 0.0

	def on_trash(self):
		"""Clean up when journey is deleted"""
		frappe.msgprint(f"Journey '{self.journey_name}' deleted")
