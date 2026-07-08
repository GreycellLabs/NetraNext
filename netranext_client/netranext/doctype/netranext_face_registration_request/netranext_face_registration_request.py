import frappe
from frappe.model.document import Document
import requests
import json


class NetraNextFaceRegistrationRequest(Document):
	@frappe.whitelist()
	def approve(self):
		"""Approve the pending face registration request"""
		if self.status != "Pending":
			frappe.throw("This request is not pending approval.")

		# 1. Update the employee's attendance_device_id
		frappe.db.set_value("Employee", self.employee, "attendance_device_id", self.face_id)

		# 2. Call Orchestrator to approve the request there
		self.sync_action_to_orchestrator(action="approve")

		# 3. Set request status to Approved
		self.status = "Approved"
		self.actioned_by = frappe.session.user
		self.actioned_date = frappe.utils.now_datetime()
		self.save()

		frappe.msgprint("Face registration request approved successfully.")

	@frappe.whitelist()
	def reject(self):
		"""Reject the pending face registration request"""
		if self.status != "Pending":
			frappe.throw("This request is not pending approval.")

		# 1. Call Orchestrator to reject the request there
		self.sync_action_to_orchestrator(action="reject")

		# 2. Set request status to Rejected
		self.status = "Rejected"
		self.actioned_by = frappe.session.user
		self.actioned_date = frappe.utils.now_datetime()
		self.save()

		frappe.msgprint("Face registration request rejected.")

	def on_trash(self):
		"""When client bench record is deleted, also delete orchestrator's copy"""
		orchestrator_name = self.orchestrator_request_name or self.name
		if not orchestrator_name:
			return

		try:
			settings = frappe.get_single("NetraNext Settings")
			if not settings.central_server_url or not settings.api_key:
				return

			try:
				api_token = settings.get_password("api_key")
			except Exception:
				api_token = settings.api_key

			url = f"{settings.central_server_url.rstrip('/')}/api/method/netranext.apis.v1.face_registration_v2.delete_face_registration_request_v2"

			headers = {
				"X-Tenant-ID": settings.tenant_id,
				"X-NetraNext-Token": api_token,
				"Content-Type": "application/json"
			}

			payload = {
				"employee_id": self.employee,
				"request_name": orchestrator_name
			}

			response = requests.post(url, json=payload, headers=headers, timeout=10)
			if response.status_code == 200:
				frappe.logger().info(f"Orchestrator request {orchestrator_name} deleted successfully")
			else:
				frappe.logger().warning(f"Failed to delete orchestrator request {orchestrator_name}: HTTP {response.status_code}")

		except Exception as e:
			# Non-fatal: log but don't block deletion on client bench
			frappe.logger().error(f"Error deleting orchestrator request on trash: {str(e)}")

	def sync_action_to_orchestrator(self, action):
		"""Call orchestrator to mirror approval/rejection"""
		settings = frappe.get_single("NetraNext Settings")
		if not settings.central_server_url or not settings.api_key:
			frappe.throw("Central Server URL or API Key is missing in NetraNext Settings.")

		# Use get_password to retrieve the plaintext key (it's stored as Password fieldtype)
		try:
			api_token = settings.get_password("api_key")
		except Exception:
			api_token = settings.api_key

		endpoint = "approve_face_registration_request_v2" if action == "approve" else "reject_face_registration_request_v2"
		url = f"{settings.central_server_url.rstrip('/')}/api/method/netranext.apis.v1.face_registration_v2.{endpoint}"

		headers = {
			"X-Tenant-ID": settings.tenant_id,
			"X-NetraNext-Token": api_token,
			"Content-Type": "application/json"
		}

		payload = {
			"employee_id": self.employee,
			"request_name": self.orchestrator_request_name or self.name,  # send orchestrator's name for doc lookup
			"face_id": self.face_id,
			"request_type": self.request_type,
			"actioned_by": frappe.session.user
		}

		try:
			response = requests.post(url, json=payload, headers=headers, timeout=15)
			if response.status_code != 200:
				res_json = response.json() if response.content else {}
				error_msg = res_json.get("message", "Unknown error")
				frappe.throw(f"Failed to sync action with Orchestrator: {error_msg} (HTTP {response.status_code})")
			
			res_data = response.json()
			if res_data.get("message", {}).get("status") == "error":
				frappe.throw(f"Orchestrator returned error: {res_data['message'].get('message')}")

		except Exception as e:
			if not isinstance(e, frappe.ValidationError):
				frappe.throw(f"Connection error to Orchestrator: {str(e)}")
			raise e
