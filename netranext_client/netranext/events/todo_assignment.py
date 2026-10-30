# Copyright (c) 2026, NetraNext and contributors
# For license information, please see license.txt

"""
ToDo assignment transition detection (Tenant Bench).

Registered in hooks.doc_events["ToDo"] for after_insert / on_update /
on_trash. Every handler is defensive: a notification failure must NEVER
break the assignment itself.

Event model (see docs/TODO_ASSIGNMENT_PUSH_NOTIFICATION_RESEARCH.md §5.1/§9.1):

- A logical event is one allocation transition: first assignment,
  reassignment to a new recipient, or reopen after Closed/Cancelled.
  Ordinary edits (description/date/priority) emit nothing.
- The logical identity is (tenant, ToDo, assignment_generation, recipient),
  materialised as an opaque `event_id` with a DB-unique constraint. Both
  the after_insert and on_update paths converge on the same id, so a hook
  firing twice (or the framework's insert-then-update sequence) can never
  double-send.
- `assignment_generation` counts recorded transitions per ToDo, so
  A -> B -> A produces a fresh generation-3 event for A instead of being
  deduplicated away.
- Close/cancel/unassign/delete does not emit a push; it INVALIDATES this
  ToDo's pending events. The Service revalidates live state before sending
  anyway, so a stale relayed event is still harmless.
"""

import hashlib

import frappe

try:
	from netranext_client.netranext.utils.logger import tenant_bench_logger
except Exception:  # pragma: no cover - logger must never break hooks
	tenant_bench_logger = None

OUTBOX_DOCTYPE = "NetraNext Assignment Outbox"

# Bounded relay window: an assignment alert older than this is stale (the
# mobile list API remains the source of truth), so stop retrying.
RELAY_WINDOW_HOURS = 24


def _log(level, message):
	if tenant_bench_logger is None:
		return
	try:
		getattr(tenant_bench_logger, level)(message, "TODO_ASSIGNMENT")
	except Exception:
		pass


def _assignment_event_id(todo_name, generation, recipient):
	"""Opaque durable identity for one logical assignment transition."""
	tenant_id = (frappe.db.get_single_value("NetraNext Settings", "tenant_id") or "").strip()
	seed = "|".join([
		tenant_id,
		str(todo_name or ""),
		str(int(generation or 0)),
		str(recipient or "").strip().lower(),
		"assigned",
	])
	return "TAE-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _next_generation(todo_name):
	"""Generation = highest recorded transition count for this ToDo + 1."""
	rows = frappe.get_all(
		OUTBOX_DOCTYPE,
		filters={"todo_name": todo_name},
		fields=["assignment_generation"],
		order_by="assignment_generation desc",
		limit=1,
		ignore_permissions=True,
	)
	if not rows:
		return 1
	return int(rows[0].assignment_generation or 0) + 1


def _record_assignment(doc):
	recipient = (doc.get("allocated_to") or "").strip()
	if not recipient:
		return
	assigned_by = (doc.get("assigned_by") or "").strip()
	# Self-assignment is already visible to the actor; Frappe's own
	# notify_assignment skips it for the same reason.
	if assigned_by and assigned_by.lower() == recipient.lower():
		return

	generation = _next_generation(doc.name)
	event_id = _assignment_event_id(doc.name, generation, recipient)
	if frappe.db.exists(OUTBOX_DOCTYPE, {"event_id": event_id}):
		return

	now = frappe.utils.now_datetime()
	frappe.get_doc({
		"doctype": OUTBOX_DOCTYPE,
		"event_id": event_id,
		"todo_name": doc.name,
		"reference_type": doc.get("reference_type") or "",
		"reference_name": doc.get("reference_name") or "",
		"recipient": recipient,
		"assigned_by": assigned_by,
		"assignment_generation": generation,
		"status": "Pending",
		"occurred_at": now,
		"next_attempt_at": now,
		"relay_deadline": frappe.utils.add_to_date(now, hours=RELAY_WINDOW_HOURS),
	}).insert(ignore_permissions=True)
	_wake_relay()


def _invalidate_open_events(todo_name, recipient=None, reason="invalidated"):
	"""Stop retrying pending events for a ToDo that changed shape.

	Optionally scoped to one recipient (reassignment) — the new assignee's
	own pending events, if any, must survive.
	"""
	filters = {"todo_name": todo_name, "status": "Pending"}
	if recipient:
		filters["recipient"] = recipient
	for name in frappe.get_all(
		OUTBOX_DOCTYPE, filters=filters, pluck="name", ignore_permissions=True
	):
		frappe.db.set_value(
			OUTBOX_DOCTYPE, name, {"status": "Invalidated", "last_error": reason}
		)


def _wake_relay():
	"""Fast path: relay right after the assignment transaction commits.

	The scheduler sweep (see utils/assignment_outbox) remains the durable
	recovery if the process dies between commit and enqueue.
	"""
	try:
		frappe.enqueue(
			"netranext_client.netranext.utils.assignment_outbox.relay_pending_assignment_events",
			queue="short",
			enqueue_after_commit=True,
		)
	except Exception:
		pass  # sweep recovers


def on_todo_after_insert(doc, method=None):
	try:
		if _is_open_assignment(doc):
			_record_assignment(doc)
	except Exception as e:
		_log("error", "after_insert assignment capture failed: {}".format(type(e).__name__))


def on_todo_update(doc, method=None):
	try:
		previous = doc.get_doc_before_save()
		if previous is None:
			# Insert paths (some Frappe versions run on_update right after
			# after_insert) have no before-save state to compare against;
			# after_insert already recorded the initial assignment.
			return

		old_recipient = (previous.get("allocated_to") or "").strip()
		new_recipient = (doc.get("allocated_to") or "").strip()
		old_status = previous.get("status") or ""
		new_status = doc.get("status") or ""

		if new_status != "Open" or not new_recipient:
			_invalidate_open_events(
				doc.name,
				reason="todo_closed" if new_status != "Open" else "todo_unassigned",
			)
			return

		recipient_changed = bool(new_recipient) and new_recipient.lower() != old_recipient.lower()
		if recipient_changed:
			if old_recipient:
				# The previous assignee's pending alerts no longer describe
				# current state; the new assignee gets a fresh-generation event.
				_invalidate_open_events(doc.name, recipient=old_recipient, reason="reassigned")
			_record_assignment(doc)
			return

		reopened = old_status in ("Closed", "Cancelled") and new_status == "Open"
		if reopened:
			_record_assignment(doc)
		# Ordinary edits (description/date/priority/role changes) intentionally
		# emit nothing — push is for allocation transitions only.
	except Exception as e:
		_log("error", "on_update assignment capture failed: {}".format(type(e).__name__))


def on_todo_trash(doc, method=None):
	try:
		_invalidate_open_events(doc.name, reason="todo_deleted")
	except Exception as e:
		_log("error", "on_trash assignment invalidation failed: {}".format(type(e).__name__))


def _is_open_assignment(doc):
	return (doc.get("status") or "Open") == "Open" and bool((doc.get("allocated_to") or "").strip())
