import frappe
from netranext_client.netranext.apis.v1.sync import store_attendance

def execute():
    print("--- Starting Geofencing and Location Check-in Approval Test ---")

    # 1. Get an active employee
    employee = frappe.db.get_value("Employee", {"status": "Active"})
    if not employee:
        print("Error: No active employee found.")
        return
    print(f"Using Employee: {employee}")

    # Set supervisor for Employee if not set, to test ToDo allocation
    emp_doc = frappe.get_doc("Employee", employee)
    if not emp_doc.reports_to:
        # Find another active employee to set as supervisor
        supervisor = frappe.db.get_value("Employee", {"name": ["!=", employee], "status": "Active"})
        if supervisor:
            emp_doc.reports_to = supervisor
            emp_doc.save(ignore_permissions=True)
            frappe.db.commit()
            print(f"Set Supervisor for {employee} to {supervisor}")
        else:
            print("Warning: Only one active employee found, cannot test supervisor assignment.")

    # Get supervisor user to verify ToDo allocation later
    supervisor_user = None
    if emp_doc.reports_to:
        supervisor_user = frappe.db.get_value("Employee", emp_doc.reports_to, "user_id")
        if not supervisor_user:
            # Set a dummy/Administrator user ID for supervisor for testing ToDo
            frappe.db.set_value("Employee", emp_doc.reports_to, "user_id", "Administrator")
            supervisor_user = "Administrator"
            print(f"Set Supervisor User ID to Administrator for testing")

    # 2. Clean up any existing test location
    test_loc_name = "Test Geofence Office"
    if frappe.db.exists("NetraNext Location", test_loc_name):
        emp_doc = frappe.get_doc("Employee", employee)
        emp_doc.custom_assigned_locations = []
        emp_doc.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.delete_doc("NetraNext Location", test_loc_name, ignore_permissions=True)
        frappe.db.commit()
        print("Cleaned up old test location.")

    # 3. Create a test location
    # Latitude/Longitude for the test office (e.g., center of London/New York or arbitrary coordinates)
    office_lat = 40.7128
    office_lon = -74.0060
    radius = 100 # meters

    loc_doc = frappe.get_doc({
        "doctype": "NetraNext Location",
        "location_name": test_loc_name,
        "latitude": office_lat,
        "longitude": office_lon,
        "radius_meters": radius,
        "address": "123 Test Street, New York"
    })
    loc_doc.insert(ignore_permissions=True)
    frappe.db.commit()
    print(f"Created Test Location: {test_loc_name} at ({office_lat}, {office_lon}) with radius {radius}m")

    # 4. Assign the location to the employee
    emp_doc = frappe.get_doc("Employee", employee)
    # Clear existing assigned locations to start fresh
    emp_doc.custom_assigned_locations = []
    emp_doc.append("custom_assigned_locations", {
        "location": test_loc_name
    })
    emp_doc.save(ignore_permissions=True)
    frappe.db.commit()
    print(f"Assigned {test_loc_name} to employee {employee}")

    # Helper function to mock sync token headers
    # We bypass token validation by mock setting incoming token
    settings = frappe.get_single("NetraNext Settings")
    token = settings.get_password("api_key")
    if not token:
        # Save a temporary token
        settings.api_key = "test_token"
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        # Reload to get password decrypted
        settings = frappe.get_single("NetraNext Settings")
        token = settings.get_password("api_key")
    
    # Mock frappe.get_request_header to return the expected token
    frappe.get_request_header = lambda key: token if key == "X-NetraNext-Token" else None

    # 5. TEST CASE A: Check-in INSIDE geofence (directly approved)
    # Coordinates inside radius: 40.7129, -74.0059 (approx 14 meters away)
    inside_lat = 40.7129
    inside_lon = -74.0059
    print(f"\n--- Running Test Case A: Check-in INSIDE geofence at ({inside_lat}, {inside_lon}) ---")
    
    att_data_inside = {
        "employee_id": employee,
        "time": frappe.utils.now_datetime().isoformat(),
        "log_type": "IN",
        "latitude": inside_lat,
        "longitude": inside_lon,
        "device_id": "Test Device"
    }

    res_inside = store_attendance(att_data_inside)
    print(f"API Response: {res_inside}")
    
    checkin_id_inside = res_inside.get("data", {}).get("checkin_id")
    if checkin_id_inside:
        checkin_doc = frappe.get_doc("Employee Checkin", checkin_id_inside)
        print(f"Created Checkin: {checkin_doc.name}")
        print(f"skip_auto_attendance = {checkin_doc.skip_auto_attendance} (Expected: 0)")
        print(f"custom_location_status = {checkin_doc.custom_location_status} (Expected: Approved)")
        
        assert checkin_doc.skip_auto_attendance == 0, "Test A Failed: skip_auto_attendance should be 0"
        assert checkin_doc.custom_location_status == "Approved", "Test A Failed: custom_location_status should be Approved"
        print("SUCCESS: Test Case A passed!")
    else:
        print("FAILED: Could not create inside check-in.")

    # 6. TEST CASE B: Check-in OUTSIDE geofence (pending approval)
    # Coordinates outside radius: 40.7200, -74.0100 (approx 860 meters away)
    outside_lat = 40.7200
    outside_lon = -74.0100
    print(f"\n--- Running Test Case B: Check-in OUTSIDE geofence at ({outside_lat}, {outside_lon}) ---")
    
    att_data_outside = {
        "employee_id": employee,
        "time": frappe.utils.now_datetime().isoformat(),
        "log_type": "OUT",
        "latitude": outside_lat,
        "longitude": outside_lon,
        "device_id": "Test Device"
    }

    res_outside = store_attendance(att_data_outside)
    print(f"API Response: {res_outside}")
    
    checkin_id_outside = res_outside.get("data", {}).get("checkin_id")
    if checkin_id_outside:
        checkin_doc = frappe.get_doc("Employee Checkin", checkin_id_outside)
        print(f"Created Checkin: {checkin_doc.name}")
        print(f"skip_auto_attendance = {checkin_doc.skip_auto_attendance} (Expected: 1)")
        print(f"custom_location_status = {checkin_doc.custom_location_status} (Expected: Pending Approval)")
        
        assert checkin_doc.skip_auto_attendance == 1, "Test B Failed: skip_auto_attendance should be 1"
        assert checkin_doc.custom_location_status == "Pending Approval", "Test B Failed: custom_location_status should be Pending Approval"
        
        # Verify Approval Request DocType was created
        approval_requests = frappe.get_all("NetraNext Location Checkin Approval", filters={
            "employee_checkin": checkin_doc.name
        }, fields=["name", "status"])
        
        assert len(approval_requests) > 0, "Test B Failed: Approval request was not created"
        approval_req = approval_requests[0]
        print(f"Found Approval Request: {approval_req.name} with status {approval_req.status} (Expected: Pending)")
        assert approval_req.status == "Pending", "Test B Failed: status should be Pending"
        
        # Verify ToDos were created for Supervisor/HR
        todos = frappe.get_all("ToDo", filters={
            "reference_type": "NetraNext Location Checkin Approval",
            "reference_name": approval_req.name,
            "status": "Open"
        }, fields=["name", "allocated_to"])
        
        print(f"Found {len(todos)} open ToDos assigned to: {[t.allocated_to for t in todos]}")
        assert len(todos) > 0, "Test B Failed: No ToDos created"
        
        # 7. TEST CASE C: Approve the request and verify
        print(f"\n--- Running Test Case C: Approving Request {approval_req.name} ---")
        
        # Simulate approval
        approval_doc = frappe.get_doc("NetraNext Location Checkin Approval", approval_req.name)
        approval_doc.status = "Approved"
        approval_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        # Refresh documents
        checkin_doc = frappe.get_doc("Employee Checkin", checkin_id_outside)
        print(f"After Approval: skip_auto_attendance = {checkin_doc.skip_auto_attendance} (Expected: 0)")
        print(f"After Approval: custom_location_status = {checkin_doc.custom_location_status} (Expected: Approved)")
        
        assert checkin_doc.skip_auto_attendance == 0, "Test C Failed: skip_auto_attendance should update to 0"
        assert checkin_doc.custom_location_status == "Approved", "Test C Failed: custom_location_status should update to Approved"
        
        # Verify ToDos are closed
        closed_todos = frappe.get_all("ToDo", filters={
            "reference_type": "NetraNext Location Checkin Approval",
            "reference_name": approval_req.name,
            "status": "Open"
        })
        print(f"Open ToDos remaining: {len(closed_todos)} (Expected: 0)")
        assert len(closed_todos) == 0, "Test C Failed: ToDos were not closed"
        
        print("SUCCESS: Test Case B and C passed!")
    else:
        print("FAILED: Could not create outside check-in.")

    # 8. Clean up
    emp_doc = frappe.get_doc("Employee", employee)
    emp_doc.custom_assigned_locations = []
    emp_doc.save(ignore_permissions=True)
    frappe.db.delete("NetraNext Employee Location", {"location": test_loc_name})
    frappe.db.commit()
    frappe.delete_doc("NetraNext Location", test_loc_name, ignore_permissions=True)
    frappe.db.commit()
    print("\n--- Test Cleaned up successfully ---")
    print("ALL TESTS PASSED!")
