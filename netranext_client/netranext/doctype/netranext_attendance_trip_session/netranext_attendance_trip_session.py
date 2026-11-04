# Copyright (c) 2026
# License: MIT - see LICENSE for details

import frappe
from frappe.model.document import Document

# Terminal session statuses - no further state transitions are allowed.
SESSION_TERMINAL_STATUSES = ("completed", "cancelled", "expired")


class NetraNextAttendanceTripSession(Document):
    def validate(self):
        self.validate_status_transitions()

    def validate_status_transitions(self):
        """Guard against doc-level edits rewinding a terminal session.

        The state machine itself lives in netranext.apis.v1.attendance_tracking;
        this hook only rejects direct writes that would resurrect a finished
        session or clear its journey link while the trip is still active.
        """
        if self.is_new():
            return
        previous = self.get_doc_before_save()
        if not previous:
            return
        if previous.status in SESSION_TERMINAL_STATUSES and self.status != previous.status:
            frappe.throw(
                "Session {0} is already {1} and cannot move to {2}.".format(
                    self.name, previous.status, self.status
                )
            )
        if (
            previous.journey
            and self.status == "trip_active"
            and not self.journey
        ):
            frappe.throw(
                "Cannot clear the journey of an active attendance-trip session."
            )
