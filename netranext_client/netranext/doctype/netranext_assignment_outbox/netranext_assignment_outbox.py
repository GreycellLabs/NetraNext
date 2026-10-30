# Copyright (c) 2026, NetraNext and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class NetraNextAssignmentOutbox(Document):
	"""
	Transactional-outbox record for a ToDo assignment transition.

	Created in the SAME transaction as the ToDo insert/update that produced
	it, so a rolled-back assignment never leaves a push event behind. The
	relay worker (netranext.utils.assignment_outbox) forwards committed
	events to the Service Server; `event_id` is the durable logical identity
	the Service deduplicates on.

	Lifecycle:
	  Pending    -> Relayed    (Service durably accepted the event)
	  Pending    -> Failed     (rejections, or relay deadline/attempts exhausted)
	  Pending    -> Invalidated(ToDo reassigned/closed/deleted before relay —
	                           the Service revalidates anyway, this only stops
	                           pointless retries)
	"""

	def before_insert(self):
		if not self.occurred_at:
			self.occurred_at = frappe.utils.now_datetime()
