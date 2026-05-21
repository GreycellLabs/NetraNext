import frappe
from frappe.model.document import Document
import uuid


class NetraNextFaceRegistration(Document):
	def before_save(self):
		"""Generate unique Face ID if not exists"""
		if not self.face_id:
			self.face_id = str(uuid.uuid4())

		# Set registered date if not exists
		if not self.registered_date:
			self.registered_date = frappe.utils.now()

	def validate(self):
		"""Validate face registration"""
		self.validate_employee()
		self.validate_duplicate_face()

	def validate_employee(self):
		"""Validate employee exists and is active"""
		if not self.employee:
			frappe.throw("Employee is required")

		employee = frappe.get_doc("Employee", self.employee)
		if employee.status != "Active":
			frappe.throw("Cannot register face for inactive employee")

	def validate_duplicate_face(self):
		"""Check for duplicate face registration"""
		existing = frappe.db.exists(
			"NetraNext Face Registration",
			{"employee": self.employee, "name": ["!=", self.name]}
		)
		if existing:
			frappe.throw("Face already registered for this employee")

	def on_trash(self):
		"""Clean up when face registration is deleted"""
		frappe.msgprint(f"Face registration deleted for {self.employee_name}")
