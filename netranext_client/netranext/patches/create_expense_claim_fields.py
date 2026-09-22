import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

EXPENSE_CLAIM_CUSTOM_FIELDS = {
    "Expense Claim": [
        {
            "fieldname": "custom_trip_details_section",
            "fieldtype": "Section Break",
            "label": "NetraNext Trip Details",
            "insert_after": "remark",
        },
        {
            "fieldname": "custom_reference_trip",
            "fieldtype": "Link",
            "label": "Reference Trip",
            "options": "NetraNext Journey",
            "insert_after": "custom_trip_details_section",
            "read_only": 1,
            "description": "Journey that generated this claim automatically",
        },
        {
            "fieldname": "custom_trip_col_break",
            "fieldtype": "Column Break",
            "insert_after": "custom_reference_trip",
        },
        {
            "fieldname": "custom_distance_km",
            "fieldtype": "Float",
            "label": "Distance (km)",
            "insert_after": "custom_trip_col_break",
            "read_only": 1,
        },
        {
            "fieldname": "custom_rate_per_km",
            "fieldtype": "Currency",
            "label": "Rate / km",
            "insert_after": "custom_distance_km",
            "read_only": 1,
        },
    ]
}


def execute():
    """
    Add trip-reference custom fields to the HRMS Expense Claim DocType.

    These back the automatic trip expense claim generation:
    - custom_reference_trip: exact one-claim-per-journey link (dedup key)
    - custom_distance_km / custom_rate_per_km: figures shown on the claim and
      in the Expense Claim List page.

    create_custom_fields is idempotent — safe on every migrate.
    """
    try:
        create_custom_fields(EXPENSE_CLAIM_CUSTOM_FIELDS, ignore_validate=True)
        frappe.db.commit()
        frappe.logger().info("Expense Claim trip custom fields ensured (netranext_client).")
    except Exception as e:
        frappe.logger().error(f"Error creating Expense Claim custom fields (netranext_client): {e}")
