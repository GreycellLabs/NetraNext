import json
import frappe

def main():
    print("=== NetraNext Trip Inserter & Page Migrator ===")
    
    # 1. Register/Ensure Page 'netranext-trip-details' exists in DB
    page_name = "netranext-trip-details"
    if not frappe.db.exists("Page", page_name):
        print(f"Creating Page record: {page_name}...")
        page_doc = frappe.get_doc({
            "doctype": "Page",
            "name": page_name,
            "page_name": page_name,
            "title": "Trip Details & Telemetry",
            "module": "NetraNext",
            "standard": "Yes",
            "system_page": 1,
            "roles": [{"role": "System Manager"}, {"role": "HR Manager"}, {"role": "HR User"}, {"role": "All"}]
        })
        frappe.flags.in_test = True
        page_doc.db_insert()
        frappe.flags.in_test = False
        print(f"Successfully created Page doc: {page_name}")
    else:
        print(f"Page record {page_name} already registered in database.")

    # 2. Get or find active employee for brinda@gmail.com
    user_email = "brinda@gmail.com"
    employee_id = frappe.db.get_value("Employee", {"user_id": user_email}, "name")
    if not employee_id:
        employee_id = frappe.db.get_value("Employee", {}, "name")
    if not employee_id:
        # Create fallback test employee if none exists
        emp = frappe.get_doc({
            "doctype": "Employee",
            "first_name": "Brinda",
            "last_name": "Ponkiya",
            "user_id": user_email,
            "company": frappe.defaults.get_user_default("company") or frappe.db.get_value("Company", {}, "name") or "NetraNext"
        })
        emp.insert(ignore_permissions=True)
        employee_id = emp.name
        print(f"Created fallback Employee: {employee_id}")

    # 3. Payload provided by user
    log_data = {
        "flutter_journey_id": "e77ced57-74f3-491d-8fab-ed6b06989beb_brinda@gmail.com",
        "is_active": False,
        "start_address": "21, Ahmedabad, Gujarat",
        "end_address": "21, Jodhpur Village, Ahmedabad",
        "destination_address": None,
        "reason": None,
        "flutter_data": {
            "id": "e77ced57-74f3-491d-8fab-ed6b06989beb_brinda@gmail.com",
            "tripId": None,
            "userId": "brinda@gmail.com",
            "startDate": "2026-09-10T06:33:46.397699Z",
            "endDate": "2026-09-10T06:33:57.530155Z",
            "isActive": False,
            "status": "Completed",
            "startAddress": "21, Ahmedabad, Gujarat",
            "endAddress": "21, Jodhpur Village, Ahmedabad",
            "destinationAddress": None,
            "reason": None,
            "metadata": {
                "end_reason": "MANUAL_USER_BUTTON_TAP",
                "ended_at": "2026-09-10T06:33:57.529977Z",
                "telemetry": {
                    "battery": {
                        "start_level": 82,
                        "end_level": 82,
                        "battery_saver_active": False,
                        "total_consumed_pct": 0
                    },
                    "network_events": [],
                    "gps_stats": {
                        "total_points_captured": 1
                    },
                    "device": {
                        "model": "RMX2020",
                        "os_version": "android RMX2020_11_C.12",
                        "network_type_at_start": "wifi"
                    }
                }
            },
            "points": [
                {"latitude": 23.0114812, "longitude": 72.5233873, "timestamp": "2026-09-10T06:33:46.397708Z"},
                {"latitude": 23.0114812, "longitude": 72.5233873, "timestamp": "2026-09-10T06:33:46.397708Z"}
            ]
        }
    }

    flutter_journey_id = log_data["flutter_journey_id"]
    flutter_data = log_data["flutter_data"]

    # Check if Journey DocType exists
    if not frappe.db.exists("DocType", "NetraNext Journey"):
        print("Error: NetraNext Journey DocType does not exist.")
        return

    # Check if journey already exists
    existing = frappe.db.get_value("NetraNext Journey", {"flutter_journey_id": flutter_journey_id}, "name")

    doc_dict = {
        "doctype": "NetraNext Journey",
        "journey_name": "Trip Log - Brinda (10 Sep 2026)",
        "employee": employee_id,
        "journey_date": "2026-09-10",
        "start_time": "2026-09-10 06:33:46",
        "end_time": "2026-09-10 06:33:57",
        "start_location": log_data["start_address"],
        "end_location": log_address_or_coord(log_data["end_address"]),
        "status": "Completed",
        "flutter_journey_id": flutter_journey_id,
        "user_id": user_email,
        "distance_km": 0.05,
        "duration_seconds": 11,
        "metadata": json.dumps(flutter_data["metadata"]),
        "raw_gps_data": json.dumps(flutter_data["points"])
    }

    if existing:
        j_doc = frappe.get_doc("NetraNext Journey", existing)
        for k, v in doc_dict.items():
            if k != "doctype":
                j_doc.set(k, v)
        j_doc.save(ignore_permissions=True)
        print(f"Updated existing NetraNext Journey: {j_doc.name}")
        record_name = j_doc.name
    else:
        j_doc = frappe.get_doc(doc_dict)
        j_doc.insert(ignore_permissions=True)
        print(f"Created new NetraNext Journey: {j_doc.name}")
        record_name = j_doc.name

    frappe.db.commit()
    print(f"SUCCESS! Journey saved in database. Record ID: {record_name}")
    print(f"URL to view details: /app/netranext-trip-details?trip_id={record_name}")

def log_address_or_coord(val):
    return val if val else "21, Jodhpur Village, Ahmedabad"

if __name__ == "__main__":
    main()
