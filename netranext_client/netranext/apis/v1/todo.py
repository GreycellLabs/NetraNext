# Copyright (c) 2026, NetraNext and contributors
# For license information, please see license.txt

"""
ToDo assignment APIs on the Tenant Bench, called ONLY by the NetraNext
Service Server (never by mobile clients — the mobile app talks to the
Service, which proxies through here with integration credentials).

Authentication follows the strict site-identity pattern of
apis/v1/user_directory.py: constant-time comparison of X-NetraNext-Token
against NetraNext Settings.api_key, plus X-Tenant-ID equality against the
handshake-established Settings.tenant_id. The tenant ID in a header alone
is never authentication.

Endpoints:
  validate_assignment_event — dispatch-time revalidation + safe summary
                              for one outbox event (push text comes from
                              HERE, never from the relayed payload).
  get_assigned_todos        — current assigned list for a tenant user.
  get_assignment_details    — one ToDo, only when currently assigned to
                              the expected user; whitelisted fields only.
"""

import html as html_lib
import re

import frappe
import hmac

OUTBOX_DOCTYPE = "NetraNext Assignment Outbox"

TITLE_MAX_CHARS = 80
BODY_MAX_CHARS = 160
DESCRIPTION_MAX_CHARS = 2000

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _error(code, message, status, reference=None):
	frappe.local.response["http_status_code"] = status
	payload = {"status": "error", "error_code": code, "message": message, "status_code": status}
	if reference:
		payload["reference"] = reference
	return payload


def _success(data):
	return {"status": "success", "data": data}


def _validate_integration():
	"""Constant-time token check + configured tenant identity equality
	(the strict pattern from user_directory.py; validate_sync_request's
	plain `!=` comparison is deliberately NOT reused here)."""
	if not getattr(frappe.local, "request", None):
		frappe.throw("An authenticated integration request is required", frappe.PermissionError)
	incoming = frappe.get_request_header("X-NetraNext-Token") or ""
	if not incoming:
		frappe.throw("Missing Integration Token", frappe.PermissionError)
	settings = frappe.get_single("NetraNext Settings")
	stored = settings.get_password("api_key", raise_exception=False) or ""
	if not stored or not hmac.compare_digest(str(incoming).encode(), str(stored).encode()):
		frappe.throw("Invalid Integration Token", frappe.PermissionError)
	configured_tenant = (settings.tenant_id or "").strip()
	if not configured_tenant:
		frappe.throw(
			"Complete the Client Settings connection handshake with the Service.",
			frappe.PermissionError,
		)
	if (frappe.get_request_header("X-Tenant-ID") or "").strip() != configured_tenant:
		frappe.throw("The requested tenant does not match this Client site.", frappe.PermissionError)
	return configured_tenant


def _to_plain_text(value, limit):
	"""Strip markup/entities and collapse whitespace — Text Editor markup
	must never reach a push preview or mobile UI raw."""
	if not value:
		return ""
	text = html_lib.unescape(_TAG_RE.sub(" ", str(value)))
	text = _WS_RE.sub(" ", text).strip()
	return text[:limit]


def _safe_title(todo):
	reference_type = (todo.get("reference_type") or "").strip()
	reference_name = (todo.get("reference_name") or "").strip()
	if reference_type == "Scheduled Trip" and reference_name:
		destination = frappe.db.get_value("Scheduled Trip", reference_name, "destination_address")
		plain = _to_plain_text(destination, 60)
		if plain:
			return "Trip to {}".format(plain)[:TITLE_MAX_CHARS]
	if reference_type == "Task" and reference_name:
		subject = frappe.db.get_value("Task", reference_name, "subject")
		plain = _to_plain_text(subject, TITLE_MAX_CHARS)
		if plain:
			return plain
	first_line = _to_plain_text(todo.get("description"), TITLE_MAX_CHARS)
	if "/" in first_line[:1] or first_line[:1] in ("~", "`"):  # legacy workflow one-liners
		first_line = ""
	return first_line or "New task"


def _resolve_user(user_id):
	"""Canonical enabled tenant User for an allocated_to value."""
	if not user_id:
		return None
	user_id = str(user_id).strip()
	if frappe.db.exists("User", user_id):
		candidate = user_id
	else:
		candidate = frappe.db.sql(
			"select name from `tabUser` where lower(email) = lower(%(email)s) limit 1",
			{"email": user_id},
		)
		candidate = candidate[0][0] if candidate else None
	if not candidate:
		return None
	if not frappe.db.get_value("User", candidate, "enabled"):
		return None
	return candidate


def _active_employee_exists(canonical_user):
	"""Mobile recipients must map to an active Employee via Employee.user_id
	(the authoritative link — no preferred/personal email guessing)."""
	if not canonical_user or not frappe.db.exists("DocType", "Employee"):
		return False
	employees = frappe.get_all(
		"Employee",
		filters={"user_id": canonical_user},
		pluck="name",
		limit_page_length=0,
	)
	for name in employees:
		status = frappe.db.get_value("Employee", name, "status")
		if (status or "Active") == "Active":
			return True
	return False


def _todo_summary(todo):
	title = _safe_title(todo)
	description = _to_plain_text(todo.get("description"), DESCRIPTION_MAX_CHARS)
	priority = todo.get("priority") or ""
	due = frappe.utils.cstr(todo.get("date")) or ""
	return {
		"todo_name": todo.get("name"),
		"title": title,
		"preview": (description[:BODY_MAX_CHARS] + ("…" if len(description) > BODY_MAX_CHARS else "")) or title,
		"description": description,
		"priority": priority,
		"due_date": due,
		"status": todo.get("status") or "Open",
		"reference_type": todo.get("reference_type") or "",
		"reference_name": todo.get("reference_name") or "",
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def validate_assignment_event(event_id=None, todo_name=None, expected_recipient=None):
	"""Service dispatch-time revalidation.

	The Service must never build push text from the relayed payload (which
	could be stale); it asks the authoritative bench whether THIS event is
	still a current open assignment, and gets a sanitized summary back.
	"""
	try:
		_validate_integration()
		if not event_id or not todo_name or not expected_recipient:
			return _error("VALIDATION_ERROR", "event_id, todo_name and expected_recipient are required", 400)

		if not frappe.db.exists("ToDo", todo_name):
			return _success({"valid": False, "reason": "todo_deleted"})

		todo = frappe.get_doc("ToDo", todo_name, ignore_permissions=True)
		recipient = (todo.get("allocated_to") or "").strip().lower()
		if recipient != str(expected_recipient).strip().lower():
			return _success({"valid": False, "reason": "reassigned"})
		if todo.get("status") != "Open":
			return _success({"valid": False, "reason": "closed"})

		# The event must not have been invalidated (close/unassign/reassign
		# before relay). Current-assignee equality above already covers
		# reassignment regardless of relay state.
		matching = frappe.get_all(
			OUTBOX_DOCTYPE,
			filters={"event_id": event_id},
			fields=["status"],
			limit=1,
			ignore_permissions=True,
		)
		if not matching or matching[0].status == "Invalidated":
			return _success({"valid": False, "reason": "superseded"})

		canonical_user = _resolve_user(expected_recipient)
		if not canonical_user:
			return _success({"valid": False, "reason": "user_missing_or_disabled"})
		if not _active_employee_exists(canonical_user):
			return _success({"valid": False, "reason": "no_active_employee"})

		return _success({"valid": True, "summary": _todo_summary(todo), "canonical_user": canonical_user})
	except frappe.PermissionError as e:
		return _error("AUTHENTICATION_ERROR", str(e), 401)
	except Exception as e:
		reference = frappe.utils.random_string(8).lower()
		frappe.log_error(
			title="ToDo Assignment Validation Failed",
			message="ref={0} {1}: {2}".format(reference, type(e).__name__, str(e)),
		)
		return _error("TODO_VALIDATION_FAILED", "Validation failed. Reference: {0}".format(reference), 500, reference)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_assigned_todos(user_id=None, status_filter="Open", limit=50, offset=0):
	"""Current assigned ToDo list for a tenant user (mobile list proxy)."""
	try:
		_validate_integration()
		if not user_id:
			return _error("VALIDATION_ERROR", "user_id is required", 400)
		canonical_user = _resolve_user(user_id)
		if not canonical_user:
			return _success({"todos": [], "user_resolved": False})

		filters = {"allocated_to": canonical_user}
		status_filter = (status_filter or "Open").strip()
		if status_filter and status_filter.lower() != "all":
			filters["status"] = status_filter

		limit = min(max(int(limit or 50), 1), 200)
		offset = max(int(offset or 0), 0)
		todos = frappe.get_all(
			"ToDo",
			filters=filters,
			fields=[
				"name", "description", "allocated_to", "assigned_by", "assigned_by_full_name",
				"reference_type", "reference_name", "status", "priority", "date",
			],
			order_by="creation desc",
			limit_start=offset,
			limit_page_length=limit,
			ignore_permissions=True,
		)
		return _success({
			"user_resolved": True,
			"todos": [_todo_summary(todo) for todo in todos],
		})
	except frappe.PermissionError as e:
		return _error("AUTHENTICATION_ERROR", str(e), 401)
	except Exception as e:
		reference = frappe.utils.random_string(8).lower()
		frappe.log_error(
			title="ToDo List Fetch Failed",
			message="ref={0} {1}: {2}".format(reference, type(e).__name__, str(e)),
		)
		return _error("TODO_LIST_FAILED", "List fetch failed. Reference: {0}".format(reference), 500, reference)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_assignment_details(user_id=None, todo_name=None):
	"""One ToDo, only if currently assigned to the expected user.

	Details are returned even for Closed/Cancelled ToDos (read-only
	reconciliation after a stale tap), but NEVER for a ToDo allocated to
	someone else — a generic not-found error avoids leaking existence.
	"""
	try:
		_validate_integration()
		if not user_id or not todo_name:
			return _error("VALIDATION_ERROR", "user_id and todo_name are required", 400)

		if not frappe.db.exists("ToDo", todo_name):
			return _error("NOT_FOUND", "Assignment not found", 404)
		todo = frappe.get_doc("ToDo", todo_name, ignore_permissions=True)

		allocated = (todo.get("allocated_to") or "").strip().lower()
		if allocated != str(user_id).strip().lower():
			return _error("NOT_FOUND", "Assignment not found", 404)

		summary = _todo_summary(todo)
		summary["assigned_by_name"] = _to_plain_text(todo.get("assigned_by_full_name"), 80)
		# Whitelisted reference adapters only — never a generic document proxy.
		if summary["reference_type"] == "Scheduled Trip" and summary["reference_name"]:
			trip = frappe.db.get_value(
				"Scheduled Trip",
				summary["reference_name"],
				["destination_address", "scheduled_start_time", "scheduled_end_time", "status"],
				as_dict=True,
			)
			if trip:
				summary["reference_detail"] = {
					"destination": _to_plain_text(trip.destination_address, 120),
					"scheduled_start_time": frappe.utils.cstr(trip.scheduled_start_time),
					"scheduled_end_time": frappe.utils.cstr(trip.scheduled_end_time),
					"trip_status": trip.status or "",
				}
		return _success(summary)
	except frappe.PermissionError as e:
		return _error("AUTHENTICATION_ERROR", str(e), 401)
	except Exception as e:
		reference = frappe.utils.random_string(8).lower()
		frappe.log_error(
			title="ToDo Detail Fetch Failed",
			message="ref={0} {1}: {2}".format(reference, type(e).__name__, str(e)),
		)
		return _error("TODO_DETAIL_FAILED", "Detail fetch failed. Reference: {0}".format(reference), 500, reference)
