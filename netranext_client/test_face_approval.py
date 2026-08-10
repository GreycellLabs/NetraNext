import frappe
from netranext_client.netranext.apis.v1.sync import store_attendance

def execute():
    print("--- Starting Face Check-in Approval Test ---")

    # 1. Get an active employee
    employee = frappe.db.get_value("Employee", {"status": "Active"})
    if not employee:
        print("Error: No active employee found.")
        return
    print(f"Using Employee: {employee}")

    # Helper function to mock sync token headers
    settings = frappe.get_single("NetraNext Settings")
    token = settings.get_password("api_key")
    if not token:
        settings.api_key = "test_token"
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        settings = frappe.get_single("NetraNext Settings")
        token = settings.get_password("api_key")
    
    # Mock frappe.get_request_header to bypass sync token checks
    frappe.get_request_header = lambda key: token if key == "X-NetraNext-Token" else None

    # 2. Clean up any previous test approvals
    frappe.db.delete("NetraNext Face Checkin Approval", {"employee": employee})
    frappe.db.commit()

    # 3. TEST CASE A: Submit a provisional check-in (pending face approval)
    print("\n--- Running Test Case A: Submit Provisional Check-in ---")
    
    att_data = {
        "employee_id": employee,
        "time": frappe.utils.now_datetime().isoformat(),
        "log_type": "IN",
        "custom_face_status": "Pending Approval",
        "custom_face_failure_reason": "Match Failure",
        "device_id": "Test Device",
        "photo_proof": "http://netranext-service.local:8000/files/test_face.jpg"
    }

    res = store_attendance(att_data)
    print(f"API Response: {res}")
    
    checkin_id = res.get("data", {}).get("checkin_id")
    assert checkin_id, "Test A Failed: Could not create provisional check-in."
    
    checkin_doc = frappe.get_doc("Employee Checkin", checkin_id)
    print(f"Created Checkin: {checkin_doc.name}")
    print(f"skip_auto_attendance = {checkin_doc.skip_auto_attendance} (Expected: 1)")
    print(f"custom_face_status = {checkin_doc.custom_face_status} (Expected: Pending Approval)")
    print(f"custom_face_failure_reason = {checkin_doc.custom_face_failure_reason} (Expected: Match Failure)")
    
    assert checkin_doc.skip_auto_attendance == 1, "Test A Failed: skip_auto_attendance should be 1"
    assert checkin_doc.custom_face_status == "Pending Approval", "Test A Failed: custom_face_status should be Pending Approval"
    assert checkin_doc.custom_face_failure_reason == "Match Failure", "Test A Failed: custom_face_failure_reason should be Match Failure"
    
    # Verify Approval Request DocType was created
    approval_requests = frappe.get_all("NetraNext Face Checkin Approval", filters={
        "employee_checkin": checkin_doc.name
    }, fields=["name", "status", "failure_reason"])
    
    assert len(approval_requests) > 0, "Test A Failed: Face Checkin Approval request was not created"
    approval_req = approval_requests[0]
    print(f"Found Approval Request: {approval_req.name} with status {approval_req.status} (Expected: Pending)")
    assert approval_req.status == "Pending", "Test A Failed: status should be Pending"
    assert approval_req.failure_reason == "Match Failure", "Test A Failed: failure_reason should be Match Failure"
    print("SUCCESS: Test Case A passed!")

    # 4. TEST CASE B: Approve the request and verify release
    print(f"\n--- Running Test Case B: Approving Request {approval_req.name} ---")
    
    approval_doc = frappe.get_doc("NetraNext Face Checkin Approval", approval_req.name)
    approval_doc.status = "Approved"
    approval_doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    # Refresh check-in and verify release
    checkin_doc = frappe.get_doc("Employee Checkin", checkin_id)
    print(f"After Approval: skip_auto_attendance = {checkin_doc.skip_auto_attendance} (Expected: 0)")
    print(f"After Approval: custom_face_status = {checkin_doc.custom_face_status} (Expected: Approved)")
    
    assert checkin_doc.skip_auto_attendance == 0, "Test B Failed: skip_auto_attendance should update to 0"
    assert checkin_doc.custom_face_status == "Approved", "Test B Failed: custom_face_status should update to Approved"
    
    # 5. Clean up
    frappe.delete_doc("NetraNext Face Checkin Approval", approval_req.name, ignore_permissions=True)
    frappe.delete_doc("Employee Checkin", checkin_id, ignore_permissions=True)
    frappe.db.commit()
    print("\n--- Test Cleaned up successfully ---")
    print("ALL TESTS PASSED!")
