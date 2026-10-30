# Copyright (c) 2026, NetraNext and contributors
# For license information, please see license.txt

"""
Transactional-outbox relay: forwards committed NetraNext Assignment Outbox
events to the NetraNext Service Server.

Delivery contract (docs/TODO_ASSIGNMENT_PUSH_NOTIFICATION_RESEARCH.md §5.2/§9.2):

- Authenticated with the SAME integration credential the Service already
  knows (X-Tenant-ID + X-NetraNext-Token from NetraNext Settings, registered
  in the Service's NetraNext Tenant registry). Nothing here invents a new
  auth system.
- Idempotent: the event_id is the logical identity; the Service ACKs a
  duplicate with the original acceptance instead of creating a second job.
- Bounded: exponential backoff with jitter, capped attempts, and a relay
  deadline — an assignment whose alert could not be handed over in time is
  marked Failed (the mobile task list remains the source of truth).
- Never fatal: assignment creation/response latency is independent of
  Service/FCM availability.
"""

import random

import frappe
import requests

try:
	from netranext_client.netranext.utils.logger import tenant_bench_logger
except Exception:  # pragma: no cover
	tenant_bench_logger = None

OUTBOX_DOCTYPE = "NetraNext Assignment Outbox"
RELAY_ENDPOINT_PATH = "/api/method/netranext.apis.v1.task_notifications.receive_assignment_event"

MAX_ATTEMPTS = 8
BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 30 * 60
BATCH_LIMIT = 50


def _log(level, message):
	if tenant_bench_logger is None:
		return
	try:
		getattr(tenant_bench_logger, level)(message, "TODO_RELAY")
	except Exception:
		pass


def _service_credentials():
	"""Integration credentials from the existing handshake-owned settings."""
	settings = frappe.get_single("NetraNext Settings")
	token = settings.get_password("api_key", raise_exception=False) or ""
	central_url = (settings.central_server_url or "").strip()
	tenant_id = (settings.tenant_id or "").strip()
	if not token or not central_url or not tenant_id:
		return None
	return {
		"integration_token": token,
		"central_server_url": central_url.rstrip("/"),
		"tenant_id": tenant_id,
	}


def relay_pending_assignment_events():
	"""Relay due Pending events. Entry points: after-commit enqueue (fast
	path) and the scheduler sweep (durable recovery — see hooks.py)."""
	now = frappe.utils.now_datetime()
	due = frappe.get_all(
		OUTBOX_DOCTYPE,
		filters={"status": "Pending", "next_attempt_at": ["<=", now]},
		pluck="name",
		order_by="creation asc",
		limit=BATCH_LIMIT,
		ignore_permissions=True,
	)
	for name in due:
		try:
			_relay_one(name, now)
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			_log("error", "relay crash for {}: {}".format(name, type(e).__name__))


def _relay_one(event_name, now):
	event = frappe.get_doc(OUTBOX_DOCTYPE, event_name, ignore_permissions=True)
	if event.status != "Pending":
		return  # invalidated between discovery and here

	deadline = frappe.utils.get_datetime(event.relay_deadline) if event.relay_deadline else None
	if deadline and now >= deadline:
		_finish(event, "Failed", "relay_deadline_exceeded")
		return

	creds = _service_credentials()
	if not creds:
		# Not configured yet: back off without burning attempts — the
		# deadline still bounds the wait.
		_schedule_retry(event, now, "central server credentials not configured", count_attempt=False)
		return

	payload = {
		"schema_version": "1",
		"event_id": event.event_id,
		"tenant_id": creds["tenant_id"],
		"todo_name": event.todo_name,
		"reference_type": event.reference_type or "",
		"reference_name": event.reference_name or "",
		"recipient": event.recipient,
		"assigned_by": event.assigned_by or "",
		"assignment_generation": int(event.assignment_generation or 1),
		"occurred_at": frappe.utils.cstr(event.occurred_at),
	}
	url = creds["central_server_url"] + RELAY_ENDPOINT_PATH
	headers = {
		"X-Tenant-ID": creds["tenant_id"],
		"X-NetraNext-Token": creds["integration_token"],
		"Content-Type": "application/json",
	}

	try:
		response = requests.post(url, json=payload, headers=headers, timeout=15)
	except requests.RequestException as e:
		_schedule_retry(event, now, "transport:{}".format(type(e).__name__))
		return

	try:
		body = response.json()
	except ValueError:
		body = {}
	message = body.get("message") if isinstance(body, dict) else None
	accepted = (
		response.status_code == 200
		and isinstance(message, dict)
		and message.get("status") == "success"
	)
	if accepted:
		frappe.db.set_value(OUTBOX_DOCTYPE, event.name, {
			"status": "Relayed",
			"relayed_at": now,
			"attempts": int(event.attempts or 0) + 1,
			"last_error": "",
		})
		return

	# Permanent client-side rejection (unknown tenant, bad schema, revoked
	# credential): retrying the identical request cannot succeed. Mark Failed
	# so the operator sees it; 429 is throttling and stays retriable.
	if 400 <= response.status_code < 500 and response.status_code != 429:
		reason = message.get("message") if isinstance(message, dict) else None
		_finish(
			event, "Failed",
			"rejected: HTTP {} {}".format(response.status_code, reason or ""),
		)
		return

	_schedule_retry(event, now, "http:{}".format(response.status_code))


def _finish(event, status, reason):
	frappe.db.set_value(OUTBOX_DOCTYPE, event.name, {
		"status": status,
		"last_error": reason,
		"attempts": int(event.attempts or 0) + 1,
	})


def _schedule_retry(event, now, reason, count_attempt=True):
	attempts = int(event.attempts or 0) + (1 if count_attempt else 0)
	if attempts >= MAX_ATTEMPTS:
		_finish(event, "Failed", "attempts exhausted: {}".format(reason))
		return
	# Full jitter exponential backoff, capped.
	delay = min(BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1)), BACKOFF_MAX_SECONDS)
	delay = random.uniform(delay / 2, delay)
	frappe.db.set_value(OUTBOX_DOCTYPE, event.name, {
		"attempts": attempts,
		"next_attempt_at": frappe.utils.add_to_date(now, seconds=int(delay)),
		"last_error": reason,
	})
