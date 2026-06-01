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

	def on_update(self):
		"""Check status change to generate expense claim"""
		if self.has_value_changed('status') and self.status == 'Completed':
			self.create_expense_claim()

	def create_expense_claim(self):
		"""Create an Expense Claim using the inbuilt module"""
		settings = frappe.get_single("NetraNext Settings")
		expense_rate = settings.expense_rate or 0.0

		if not expense_rate or not self.distance_km:
			frappe.msgprint("Expense Claim not created: Distance is 0 or Expense Rate is not configured in NetraNext Settings.")
			return

		expense_amount = self.distance_km * expense_rate

		try:
			employee = frappe.get_doc("Employee", self.employee)
			
			expense_claim = frappe.new_doc("Expense Claim")
			expense_claim.employee = self.employee
			expense_claim.company = employee.company
			expense_claim.posting_date = frappe.utils.nowdate()
			
			if settings.expense_approver:
				expense_claim.expense_approver = settings.expense_approver
			
			expense_claim.append("expenses", {
				"expense_type": "Travel",
				"amount": expense_amount,
				"description": f"Automated expense for Journey: {self.journey_name} ({self.distance_km} km at rate {expense_rate})"
			})
			
			expense_claim.remark = f"Generated automatically for NetraNext Journey {self.name}"
			
			# Save as Draft (docstatus = 0 by default when inserted)
			expense_claim.insert(ignore_permissions=True)
			
			frappe.msgprint(f"Draft Expense Claim {expense_claim.name} created successfully for {expense_amount}.")
		except Exception as e:
			frappe.log_error(frappe.get_traceback(), f"Failed to create Expense Claim for Journey {self.name}")
			frappe.msgprint(f"Failed to create Expense Claim: {str(e)}")
