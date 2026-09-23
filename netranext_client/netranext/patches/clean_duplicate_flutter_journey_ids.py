import frappe

def execute():
    """
    Clean up duplicate flutter_journey_id values in tabNetraNext Journey
    before doctype schema alter adds the UNIQUE index constraint.
    """
    if not frappe.db.has_table("NetraNext Journey"):
        return

    try:
        duplicates = frappe.db.sql("""
            SELECT flutter_journey_id, COUNT(*) as cnt
            FROM `tabNetraNext Journey`
            WHERE flutter_journey_id IS NOT NULL AND flutter_journey_id != ''
            GROUP BY flutter_journey_id
            HAVING cnt > 1
        """, as_dict=True)

        for dup in duplicates:
            journey_id = dup["flutter_journey_id"]
            records = frappe.get_all(
                "NetraNext Journey",
                filters={"flutter_journey_id": journey_id},
                fields=["name", "modified"],
                order_by="modified desc"
            )
            for rec in records[1:]:
                new_id = f"{journey_id}_dup_{rec['name']}"
                frappe.db.set_value("NetraNext Journey", rec["name"], "flutter_journey_id", new_id, update_modified=False)

        frappe.db.commit()
    except Exception as e:
        frappe.logger().error(f"Error cleaning duplicate flutter_journey_ids: {e}")
