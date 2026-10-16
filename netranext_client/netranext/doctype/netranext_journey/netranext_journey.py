import frappe
from frappe.model.document import Document
from frappe.utils import strip_html
import json
import re


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
		# Remove this trip's line from a Draft claim. If that was the only
		# remaining expense, delete the orphaned Draft. Submitted/Approved
		# claims are left untouched (finance history).
		try:
			self._remove_trip_from_draft_claims()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Failed to clean up Expense Claims for Journey {self.name}")

		frappe.msgprint(f"Journey '{self.journey_name}' deleted")

	def on_update(self):
		"""Check status change to generate expense claim"""
		if self.status == 'Completed':
			self.create_expense_claim()

	def create_expense_claim(self):
		"""Add this completed trip's expense to a Draft Expense Claim.

		Total = distance_km x rate (NetraNext Settings > Expense Rate per KM).

		Reuses the employee's existing NetraNext Draft claim when one exists,
		appending or updating this trip's expense row. A new claim is created
		only when there is no reusable Draft. Submitted claims are never
		duplicated for the same trip.
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

		expense_row = {
			"expense_type": expense_type,
			"expense_date": posting_date,
			"amount": expense_amount,
			"description": (
				f"Automated expense for Journey {self.name}: "
				f"{getattr(self, 'journey_name', self.name)} ({dist} km at rate {expense_rate})"
			),
		}
		if frappe.db.has_column("Expense Claim Detail", "custom_reference_trip"):
			expense_row["custom_reference_trip"] = self.name
		if frappe.db.has_column("Expense Claim Detail", "custom_distance_km"):
			expense_row["custom_distance_km"] = dist

		try:
			employee = frappe.get_doc("Employee", self.employee)

			existing_claim_name, existing_docstatus = self._find_claim_for_trip()
			if existing_claim_name and existing_docstatus != 0:
				# This trip is already on a submitted/cancelled claim — never duplicate.
				return

			draft_name = existing_claim_name if existing_docstatus == 0 else self._find_employee_draft_trip_claim()

			if draft_name:
				claim = frappe.get_doc("Expense Claim", draft_name)
				self._upsert_trip_expense_row(claim, expense_row)
				self._refresh_claim_trip_header(claim, expense_rate)
				claim.save(ignore_permissions=True)
				frappe.logger().info(
					f"Draft Expense Claim {claim.name} updated with {expense_amount} for Journey {self.name}."
				)
				return

			expense_claim = frappe.new_doc("Expense Claim")
			expense_claim.employee = self.employee
			expense_claim.company = employee.company
			expense_claim.posting_date = posting_date
			expense_claim.exchange_rate = 1.0
			expense_claim.approval_status = "Draft"

			if getattr(settings, 'expense_approver', None):
				expense_claim.expense_approver = settings.expense_approver

			if getattr(settings, 'payable_account', None):
				expense_claim.payable_account = settings.payable_account

			expense_claim.append("expenses", expense_row)
			self._refresh_claim_trip_header(expense_claim, expense_rate)

			# Save as Draft (pending approval workflow takes it from here).
			# No explicit commit: the claim commits atomically with the journey.
			expense_claim.insert(ignore_permissions=True)

			frappe.logger().info(
				f"Draft Expense Claim {expense_claim.name} created for Journey {self.name}: {dist} km x {expense_rate} = {expense_amount}."
			)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Failed to create Expense Claim for Journey {self.name}")

	def _find_claim_for_trip(self):
		"""Return (claim_name, docstatus) if this journey is already on a claim."""
		if frappe.db.has_column("Expense Claim Detail", "custom_reference_trip"):
			parent = frappe.db.get_value(
				"Expense Claim Detail",
				{"custom_reference_trip": self.name},
				"parent",
			)
			if parent:
				return parent, frappe.db.get_value("Expense Claim", parent, "docstatus")

		parent = frappe.db.sql(
			"""
			SELECT parent FROM `tabExpense Claim Detail`
			WHERE description LIKE %s
			LIMIT 1
			""",
			(f"%Journey {self.name}:%",),
		)
		if parent:
			claim_name = parent[0][0]
			return claim_name, frappe.db.get_value("Expense Claim", claim_name, "docstatus")

		# Legacy one-claim-per-trip header link
		existing = frappe.db.get_value(
			"Expense Claim",
			{"custom_reference_trip": self.name},
			["name", "docstatus"],
			as_dict=True,
		)
		if existing:
			return existing.name, existing.docstatus
		return None, None

	def _find_employee_draft_trip_claim(self):
		"""Reusable Draft claim for this employee (auto-generated trip claims only)."""
		drafts = frappe.get_all(
			"Expense Claim",
			filters={"employee": self.employee, "docstatus": 0},
			fields=["name", "custom_reference_trip", "remark", "approval_status"],
			order_by="creation asc",
		)
		for draft in drafts:
			if (draft.get("approval_status") or "Draft") != "Draft":
				continue
			is_trip_claim = bool(draft.get("custom_reference_trip"))
			remark = draft.get("remark") or ""
			if is_trip_claim or "Generated automatically for NetraNext Journey" in remark:
				return draft.name
		return None

	def _upsert_trip_expense_row(self, claim, expense_row):
		"""Update this trip's expense line, or append it if it is new."""
		existing_row = None
		for row in claim.expenses:
			if getattr(row, "custom_reference_trip", None) == self.name:
				existing_row = row
				break
			if f"Journey {self.name}:" in (row.description or ""):
				existing_row = row
				break
		if existing_row is None and claim.get("custom_reference_trip") == self.name and len(claim.expenses) == 1:
			existing_row = claim.expenses[0]

		if existing_row:
			existing_row.amount = expense_row["amount"]
			existing_row.expense_date = expense_row["expense_date"]
			existing_row.description = expense_row["description"]
			existing_row.expense_type = expense_row["expense_type"]
			if hasattr(existing_row, "custom_reference_trip"):
				existing_row.custom_reference_trip = self.name
			if hasattr(existing_row, "custom_distance_km") and "custom_distance_km" in expense_row:
				existing_row.custom_distance_km = expense_row["custom_distance_km"]
			return

		claim.append("expenses", expense_row)

	def _refresh_claim_trip_header(self, claim, expense_rate=None):
		"""Keep header trip fields in sync with all trip expense lines."""
		trips = []
		total_dist = 0.0
		for row in claim.expenses:
			trip = self._trip_id_from_expense_row(row)
			if trip:
				trips.append(trip)
			total_dist += float(getattr(row, "custom_distance_km", 0) or 0)

		claim.custom_reference_trip = trips[-1] if trips else self.name
		rate = expense_rate if expense_rate is not None else float(claim.custom_rate_per_km or 0)
		if not total_dist and rate:
			total_dist = sum(float(row.amount or 0) for row in claim.expenses) / rate
		claim.custom_distance_km = total_dist or float(
			self.distance_km or getattr(self, "calculated_odometer_distance", 0.0) or 0.0
		)
		if expense_rate is not None:
			claim.custom_rate_per_km = expense_rate
		unique_trips = list(dict.fromkeys(trips or [self.name]))
		label = "Journey" if len(unique_trips) == 1 else "Journeys"
		claim.remark = f"Generated automatically for NetraNext {label} {', '.join(unique_trips)}"

	def _remove_trip_from_draft_claims(self):
		claim_names = set(
			frappe.get_all(
				"Expense Claim",
				filters={"custom_reference_trip": self.name, "docstatus": 0},
				pluck="name",
			)
		)
		if frappe.db.has_column("Expense Claim Detail", "custom_reference_trip"):
			for parent in frappe.get_all(
				"Expense Claim Detail",
				filters={"custom_reference_trip": self.name},
				pluck="parent",
			):
				if frappe.db.get_value("Expense Claim", parent, "docstatus") == 0:
					claim_names.add(parent)

		for parent in frappe.db.sql(
			"""
			SELECT DISTINCT parent FROM `tabExpense Claim Detail`
			WHERE description LIKE %s
			""",
			(f"%Journey {self.name}:%",),
		):
			if frappe.db.get_value("Expense Claim", parent[0], "docstatus") == 0:
				claim_names.add(parent[0])

		for claim_name in claim_names:
			claim = frappe.get_doc("Expense Claim", claim_name)
			rows_to_remove = [
				row for row in claim.expenses
				if self._trip_id_from_expense_row(row) == self.name
			]
			# Legacy single-trip claim: header points at this journey
			if not rows_to_remove and claim.get("custom_reference_trip") == self.name and len(claim.expenses) == 1:
				rows_to_remove = list(claim.expenses)

			for row in rows_to_remove:
				claim.remove(row)

			if not claim.expenses:
				frappe.delete_doc("Expense Claim", claim_name, ignore_permissions=True)
			else:
				self._refresh_claim_trip_header(claim)
				claim.save(ignore_permissions=True)

	def _trip_id_from_expense_row(self, row):
		trip = getattr(row, "custom_reference_trip", None)
		if trip:
			return trip
		desc = strip_html(row.description or "")
		match = re.search(r"Journey ([^:]+):", desc)
		return match.group(1).strip() if match else None
