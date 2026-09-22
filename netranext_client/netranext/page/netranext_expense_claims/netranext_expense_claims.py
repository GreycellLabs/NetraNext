import frappe
from frappe.utils import flt


def get_context(context):
    """
    Build context for the NetraNext Expense Claim List page.
    """
    context.title = "Expense Claim List"
    context.csrf_token = frappe.sessions.get_csrf_token()
    return context


@frappe.whitelist()
def get_expense_claims(employee=None, limit=500):
    """
    Trip-generated Expense Claims for the Expense Claim List page.

    Only claims that were auto-generated from a completed trip
    (custom_reference_trip set) are returned, joined with the Employee and
    the originating Journey so the list can show trip details.

    Args:
        employee (str): optional Employee filter
        limit (int): max rows (default 500)

    Returns:
        dict: {claims: [...], employees: [...], totals: {...}}
    """
    conditions = [
        "ec.custom_reference_trip IS NOT NULL",
        "ec.custom_reference_trip != ''",
    ]
    values = []
    if employee:
        conditions.append("ec.employee = %s")
        values.append(employee)

    claims = frappe.db.sql(
        f"""
        SELECT ec.name, ec.employee, ec.posting_date, ec.custom_distance_km,
               ec.custom_rate_per_km, ec.total_claimed_amount,
               ec.approval_status, ec.docstatus, ec.custom_reference_trip,
               emp.employee_name, j.start_time AS trip_start_time,
               j.status AS trip_status, j.distance_km AS journey_distance_km
        FROM `tabExpense Claim` ec
        LEFT JOIN `tabEmployee` emp ON emp.name = ec.employee
        LEFT JOIN `tabNetraNext Journey` j ON j.name = ec.custom_reference_trip
        WHERE {" AND ".join(conditions)}
        ORDER BY ec.posting_date DESC, ec.creation DESC
        LIMIT %s
        """,
        tuple(values + [int(limit)]),
        as_dict=True,
    )

    total_distance = 0.0
    total_amount = 0.0
    for c in claims:
        c.posting_date = str(c.posting_date) if c.posting_date else ""
        c.trip_start_time = str(c.trip_start_time) if c.trip_start_time else ""

        # Trip Date: when the trip started (falls back to claim posting date)
        c.trip_date = (c.trip_start_time or c.posting_date or "").split(" ")[0] or c.posting_date

        c.distance_km = flt(c.custom_distance_km or c.journey_distance_km)
        c.rate_per_km = flt(c.custom_rate_per_km)
        c.total_amount = flt(c.total_claimed_amount)

        # Unified status for display
        if c.docstatus == 2:
            c.status = "Cancelled"
        elif c.docstatus == 1:
            c.status = c.approval_status or "Submitted"
        else:
            c.status = "Draft"

        total_distance += c.distance_km
        total_amount += c.total_amount

    # Employee options for the filter dropdown
    employees = frappe.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=["name", "employee_name"],
        order_by="employee_name asc",
        limit_page_length=0,
    )

    return {
        "claims": claims,
        "employees": employees,
        "totals": {
            "count": len(claims),
            "distance_km": round(total_distance, 2),
            "amount": round(total_amount, 2),
        },
    }
