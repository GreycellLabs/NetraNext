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
		# Delete Draft claims auto-generated for this journey so a deleted /
		# de-duplicated trip does not leave an orphaned claim behind.
		# Submitted/Approved claims are left untouched (finance history).
		try:
			linked_claims = frappe.get_all("Expense Claim", filters={
				"custom_reference_trip": self.name,
				"docstatus": 0
			}, pluck="name")
			for claim_name in linked_claims:
				frappe.delete_doc("Expense Claim", claim_name, ignore_permissions=True)
		except Exception as e:
			frappe.log_error(frappe.get_traceback(), f"Failed to clean up Expense Claims for Journey {self.name}")

		frappe.msgprint(f"Journey '{self.journey_name}' deleted")

	def on_update(self):
		"""Check status change to generate expense claim"""
		if self.status == 'Completed':
			self.create_expense_claim()

	def create_expense_claim(self):
		"""Create an Expense Claim automatically for a completed trip with distance.

		Total = distance_km x rate (NetraNext Settings > Expense Rate per KM).
		Idempotent: an exact Link field (custom_reference_trip) guarantees one
		claim per journey — a re-sync while the trip is already Completed only
		updates the Draft claim's figures instead of creating a duplicate.
		"""
		settings = frappe.get_single("NetraNext Settings")
		expense_rate = float(settings.expense_rate or 0.0)
		expense_type = settings.expense_claim_type or frappe.db.get_value("Expense Claim Type", {"expense_type": ["like", "%Travel%"]}, "name") or frappe.db.get_value("Expense Claim Type", {}, "name")

		# Calculate effective distance (either distance_km or calculated_odometer_distance)
		dist = float(self.distance_km or getattr(self, "calculated_odometer_distance", 0.0) or 0.0)

		# Zero-distance trips never generate a claim; without a configured rate
		# the claim amount would always be zero, so skip that too.
		if dist <= 0 or expense_rate <= 0 or not expense_type:
			frappe.logger().info(f"Expense Claim skipped for {self.name}: dist={dist}, rate={expense_rate}, type={expense_type}")
			return

		expense_amount = dist * expense_rate

		# Posting date = date the trip completed (fall back to journey date / today)
		posting_date = None
		for source_date in (self.end_time, getattr(self, "journey_date", None)):
			if source_date:
				posting_date = frappe.utils.getdate(source_date)
				break
		if not posting_date:
			posting_date = frappe.utils.today()

		try:
			employee = frappe.get_doc("Employee", self.employee)

			# Exactly one claim per journey: exact match on the Reference Trip
			# link field. (A LIKE match on the remark would wrongly match
			# JOURNEY-0001 against JOURNEY-00012.)
			existing_claim = frappe.db.get_value("Expense Claim", {"custom_reference_trip": self.name}, ["name", "docstatus"], as_dict=True)

			if existing_claim and existing_claim.docstatus == 0:
				# Re-sync with (possibly) corrected distance — refresh the Draft
				# claim's figures instead of creating a second one.
				claim = frappe.get_doc("Expense Claim", existing_claim.name)
				claim.custom_distance_km = dist
				claim.custom_rate_per_km = expense_rate
				if claim.expenses:
					claim.expenses[0].amount = expense_amount
					claim.expenses[0].expense_date = posting_date
					claim.expenses[0].description = f"Automated expense for Journey: {getattr(self, 'journey_name', self.name)} ({dist} km at rate {expense_rate})"
				claim.save(ignore_permissions=True)
				frappe.logger().info(f"Draft Expense Claim {claim.name} updated to {expense_amount} for Journey {self.name}.")
				return

			if existing_claim:
				# Submitted/Approved claim already exists — never duplicate.
				return

			expense_claim = frappe.new_doc("Expense Claim")
			expense_claim.employee = self.employee
			expense_claim.company = employee.company
			expense_claim.posting_date = posting_date
			expense_claim.exchange_rate = 1.0

			if getattr(settings, 'expense_approver', None):
				expense_claim.expense_approver = settings.expense_approver

			if getattr(settings, 'payable_account', None):
				expense_claim.payable_account = settings.payable_account

			expense_claim.append("expenses", {
				"expense_type": expense_type,
				"expense_date": posting_date,
				"amount": expense_amount,
				"description": f"Automated expense for Journey: {getattr(self, 'journey_name', self.name)} ({dist} km at rate {expense_rate})"
			})

			expense_claim.custom_reference_trip = self.name
			expense_claim.custom_distance_km = dist
			expense_claim.custom_rate_per_km = expense_rate
			expense_claim.remark = f"Generated automatically for NetraNext Journey {self.name}"

			# Save as Draft (pending approval workflow takes it from here).
			# No explicit commit: the claim commits atomically with the journey.
			expense_claim.insert(ignore_permissions=True)

			frappe.logger().info(f"Draft Expense Claim {expense_claim.name} created for Journey {self.name}: {dist} km x {expense_rate} = {expense_amount}.")
		except Exception as e:
			frappe.log_error(frappe.get_traceback(), f"Failed to create Expense Claim for Journey {self.name}")
