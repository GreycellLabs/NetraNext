import frappe
from datetime import datetime, timedelta
from netranext_client.netranext.apis.v1.sync import store_attendance

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
        "gender": "Male",
        "date_of_birth": "2000-01-01"
    })
    doc.insert(ignore_permissions=True)
    return doc.name

def run():
    print("==================================================")
    print("STARTING TEST FOR MULTIPLE DAILY CHECK-INS/OUTS")
    print("==================================================")

    vraj_emp_id = get_or_create_employee("Vraj Patel", "HR-EMP-VRAJ", "vraj@example.com")
    print(f"Employee: Vraj Patel ({vraj_emp_id})")

    # Clear existing checkins for this employee to start fresh
    for c in frappe.get_all("Employee Checkin", filters={"employee": vraj_emp_id}):
        frappe.delete_doc("Employee Checkin", c.name, force=True)
    frappe.db.commit()

    try:
        # 1. First Check-in (IN) at 09:00 AM (Should succeed)
        print("\n--- 1. Simulating first check-in (IN) at 09:00 AM ---")
        att_data_1 = {
            "employee_id": vraj_emp_id,
            "time": "2026-08-18 09:00:00",
            "log_type": "IN"
        }
        res_1 = store_attendance(att_data_1)
        print("Result 1:", res_1)
        assert res_1.get("status") == "success"
        assert res_1.get("data", {}).get("already_checked_in") is not True

        # 2. Consecutive Check-in (IN) at 09:05 AM (Should fail / be blocked)
        print("\n--- 2. Simulating duplicate consecutive check-in (IN) at 09:05 AM ---")
        att_data_dup_in = {
            "employee_id": vraj_emp_id,
            "time": "2026-08-18 09:05:00",
            "log_type": "IN"
        }
        res_dup_in = store_attendance(att_data_dup_in)
        print("Result Duplicate IN:", res_dup_in)
        assert res_dup_in.get("data", {}).get("already_checked_in") is True, "Consecutive check-in was not blocked!"

        # 3. First Check-out (OUT) at 05:00 PM (Should succeed)
        print("\n--- 3. Simulating first check-out (OUT) at 05:00 PM ---")
        att_data_2 = {
            "employee_id": vraj_emp_id,
            "time": "2026-08-18 17:00:00",
            "log_type": "OUT"
        }
        res_2 = store_attendance(att_data_2)
        print("Result 2:", res_2)
        assert res_2.get("status") == "success"
        assert res_2.get("data", {}).get("already_checked_in") is not True

        # 4. Consecutive Check-out (OUT) at 05:05 PM (Should fail / be blocked)
        print("\n--- 4. Simulating duplicate consecutive check-out (OUT) at 05:05 PM ---")
        att_data_dup_out = {
            "employee_id": vraj_emp_id,
            "time": "2026-08-18 17:05:00",
            "log_type": "OUT"
        }
        res_dup_out = store_attendance(att_data_dup_out)
        print("Result Duplicate OUT:", res_dup_out)
        assert res_dup_out.get("data", {}).get("already_checked_in") is True, "Consecutive check-out was not blocked!"

        # 5. Second Check-in (IN) at 06:00 PM (Should succeed!)
        print("\n--- 5. Simulating second check-in (IN) at 06:00 PM ---")
        att_data_3 = {
            "employee_id": vraj_emp_id,
            "time": "2026-08-18 18:00:00",
            "log_type": "IN"
        }
        res_3 = store_attendance(att_data_3)
        print("Result 3:", res_3)
        assert res_3.get("status") == "success"
        assert res_3.get("data", {}).get("already_checked_in") is not True, "Second check-in was incorrectly blocked!"

        # Retrieve and verify database records
        checkins = frappe.get_all("Employee Checkin", filters={"employee": vraj_emp_id}, fields=["name", "log_type", "time"], order_by="time asc")
        print(f"\nFinal check-ins in database for Vraj Patel: {len(checkins)}")
        for idx, c in enumerate(checkins):
            print(f"[{idx+1}] {c.name}: {c.log_type} at {c.time}")

        assert len(checkins) == 3, f"Expected exactly 3 check-ins in database, got {len(checkins)}"
        assert checkins[0].log_type == "IN" and str(checkins[0].time) == "2026-08-18 09:00:00"
        assert checkins[1].log_type == "OUT" and str(checkins[1].time) == "2026-08-18 17:00:00"
        assert checkins[2].log_type == "IN" and str(checkins[2].time) == "2026-08-18 18:00:00"

        print("\n==================================================")
        print("SUCCESS: TEST PASSED PROPERLY!")
        print("- Alternating check-ins/outs on the same day are fully allowed.")
        print("- Consecutive check-ins (IN -> IN) and check-outs (OUT -> OUT) are successfully blocked.")
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
        for c in frappe.get_all("Employee Checkin", filters={"employee": vraj_emp_id}):
            frappe.delete_doc("Employee Checkin", c.name, force=True)
        if frappe.db.exists("Employee", vraj_emp_id):
            frappe.delete_doc("Employee", vraj_emp_id, force=True)
        frappe.db.commit()
        print("Cleanup completed.")

if __name__ == "__main__":
    run()
