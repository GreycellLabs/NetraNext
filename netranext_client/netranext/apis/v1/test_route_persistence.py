import frappe
import json
from datetime import datetime, timedelta, timezone
from netranext_client.netranext.apis.v1.sync import store_journey

def get_or_create_employee(name, employee_id, email):
    if frappe.db.exists("Employee", employee_id):
        doc = frappe.get_doc("Employee", employee_id)
        doc.employee_name = name
        doc.first_name = name
        doc.status = "Active"
        doc.company = "brinda tech"
        doc.save(ignore_permissions=True)
        return employee_id
    
    doc = frappe.get_doc({
        "doctype": "Employee",
        "employee": employee_id,
        "employee_name": name,
        "first_name": name,
        "status": "Active",
        "company": "brinda tech",
        "personal_email": email,
        "date_of_joining": "2026-01-01",
        "gender": "Male" if name == "Jay" else "Female",
        "date_of_birth": "2000-01-01"
    })
    doc.insert(ignore_permissions=True)
    return doc.name

def create_scheduled_trip(employee_id):
    doc = frappe.get_doc({
        "doctype": "Scheduled Trip",
        "employee": employee_id,
        "status": "Scheduled",
        "destination_address": "Veishnodevi circle-Office",
        "scheduled_start_time": frappe.utils.now_datetime(),
        "scheduled_end_time": frappe.utils.now_datetime() + timedelta(hours=2)
    })
    doc.insert(ignore_permissions=True)
    return doc.name

def run():
    print("==================================================")
    print("STARTING TEST FOR ROUTE PERSISTENCE AND COEXISTENCE")
    print("==================================================")

    jay_emp_id = get_or_create_employee("Jay", "HR-EMP-JAY", "jay@example.com")
    print(f"Employee: Jay ({jay_emp_id})")

    # Trip 1 details (Gota -> ISCON)
    trip1_id = create_scheduled_trip(jay_emp_id)
    journey1_id = "flutter_journey_gota_iscon_111"
    
    # Gota -> ISCON coordinates
    gota_iscon_gps = [
        {"latitude": 23.0805, "longitude": 72.5314, "timestamp": "2026-08-17T10:00:00Z"},
        {"latitude": 23.0555, "longitude": 72.5444, "timestamp": "2026-08-17T10:05:00Z"},
        {"latitude": 23.0295, "longitude": 72.5684, "timestamp": "2026-08-17T10:10:00Z"}
    ]

    try:
        # 1. Start and complete Trip 1
        print("\n--- Simulating Trip 1: Gota -> ISCON ---")
        payload1_start = {
            "employee_id": jay_emp_id,
            "journey_id": journey1_id,
            "journey_name": "Gota to ISCON",
            "trip_id": trip1_id,
            "status": "In Progress",
            "start_time": "2026-08-17 10:00:00",
            "raw_gps_data": json.dumps(gota_iscon_gps[:2])
        }
        res_start1 = store_journey(payload1_start)
        print("Trip 1 started:", res_start1)
        frappe.db.commit()

        payload1_end = {
            "employee_id": jay_emp_id,
            "journey_id": journey1_id,
            "journey_name": "Gota to ISCON",
            "trip_id": trip1_id,
            "status": "Completed",
            "start_time": "2026-08-17 10:00:00",
            "end_time": "2026-08-17 10:10:00",
            "raw_gps_data": json.dumps(gota_iscon_gps)
        }
        res_end1 = store_journey(payload1_end)
        print("Trip 1 ended:", res_end1)
        frappe.db.commit()

        # Retrieve and verify Trip 1's route in DB
        trip1_doc_name = frappe.db.get_value("NetraNext Journey", {"flutter_journey_id": journey1_id}, "name")
        trip1_doc = frappe.get_doc("NetraNext Journey", trip1_doc_name)
        initial_route1 = json.loads(trip1_doc.raw_gps_data)
        print(f"Verified Trip 1 ({trip1_doc.name}) route. Points count: {len(initial_route1)}")
        assert len(initial_route1) == 3, f"Expected 3 points, got {len(initial_route1)}"

        # Trip 2 details (ISCON -> Gota)
        trip2_id = create_scheduled_trip(jay_emp_id)
        journey2_id = "flutter_journey_iscon_gota_222"
        
        # ISCON -> Gota coordinates
        iscon_gota_gps = [
            {"latitude": 23.0295, "longitude": 72.5684, "timestamp": "2026-08-17T11:00:00Z"},
            {"latitude": 23.0555, "longitude": 72.5444, "timestamp": "2026-08-17T11:05:00Z"},
            {"latitude": 23.0805, "longitude": 72.5314, "timestamp": "2026-08-17T11:10:00Z"}
        ]

        # 2. Start and complete Trip 2
        print("\n--- Simulating Trip 2: ISCON -> Gota ---")
        payload2_start = {
            "employee_id": jay_emp_id,
            "journey_id": journey2_id,
            "journey_name": "ISCON to Gota",
            "trip_id": trip2_id,
            "status": "In Progress",
            "start_time": "2026-08-17 11:00:00",
            "raw_gps_data": json.dumps(iscon_gota_gps[:2])
        }
        res_start2 = store_journey(payload2_start)
        print("Trip 2 started:", res_start2)
        frappe.db.commit()

        payload2_end = {
            "employee_id": jay_emp_id,
            "journey_id": journey2_id,
            "journey_name": "ISCON to Gota",
            "trip_id": trip2_id,
            "status": "Completed",
            "start_time": "2026-08-17 11:00:00",
            "end_time": "2026-08-17 11:10:00",
            "raw_gps_data": json.dumps(iscon_gota_gps)
        }
        res_end2 = store_journey(payload2_end)
        print("Trip 2 ended:", res_end2)
        frappe.db.commit()

        # 3. Check if Trip 1's route was affected by Trip 2
        print("\n--- Verifying Trip 1 persistence after Trip 2 completion ---")
        trip1_doc.reload()
        post_route1 = json.loads(trip1_doc.raw_gps_data)
        print(f"Trip 1 post-Trip 2 route points count: {len(post_route1)}")
        
        # Verify status and end_time of Trip 1
        print(f"Trip 1 status: {trip1_doc.status}, end_time: {trip1_doc.end_time}")

        # Assertions
        assert len(post_route1) == 3, f"Trip 1's route points count changed! Expected 3, got {len(post_route1)}"
        assert post_route1 == gota_iscon_gps, "Trip 1's coordinates were modified/corrupted!"
        assert trip1_doc.status == "Completed", f"Expected Trip 1 status 'Completed', got '{trip1_doc.status}'"
        
        print("\n==================================================")
        print("SUCCESS: TEST PASSED PROPERLY!")
        print("- Trip 1 route remains unchanged after Trip 2.")
        print("- Each trip has independent route data.")
        print("==================================================")

    except AssertionError as e:
        print("\n==================================================")
        print("FAILURE: TEST FAILED!")
        print(str(e))
        print("==================================================")
    except Exception as e:
        print(f"Unexpected error during test: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        print("\nCleaning up test records from database...")
        for jid in [journey1_id, journey2_id]:
            for j in frappe.get_all("NetraNext Journey", filters={"flutter_journey_id": jid}):
                frappe.delete_doc("NetraNext Journey", j.name, force=True)
        for tid in [trip1_id, trip2_id]:
            if frappe.db.exists("Scheduled Trip", tid):
                frappe.delete_doc("Scheduled Trip", tid, force=True)
        if frappe.db.exists("Employee", jay_emp_id):
            frappe.delete_doc("Employee", jay_emp_id, force=True)
        frappe.db.commit()
        print("Cleanup completed.")

if __name__ == "__main__":
    run()
