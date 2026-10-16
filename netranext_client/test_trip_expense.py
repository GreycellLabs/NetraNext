import frappe

def execute():
    print("--- Starting Trip Expense Test ---")

    # 1. Get an active employee
    employee = frappe.db.get_value("Employee", {"status": "Active"})
    if not employee:
        print("Error: No active employee found to create a journey.")
        return
    print(f"Using Employee: {employee}")

    # 2. Set Expense Rate in NetraNext Settings
    settings = frappe.get_doc("NetraNext Settings")
    settings.expense_rate = 5.0
    if not settings.expense_approver:
        # Set Administrator as default approver if none set to pass required validation
        settings.expense_approver = "Administrator"
    settings.save(ignore_permissions=True)
    frappe.db.commit()
    print(f"Set Expense Rate in NetraNext Settings to {settings.expense_rate}")

    # 3. Ensure "Travel" Expense Claim Type exists
    company = frappe.db.get_value("Employee", employee, "company")
    # Get an expense account for the company
    expense_account = frappe.db.get_value("Account", {"company": company, "account_type": "Expense Account"})
    if not expense_account:
        expense_account = frappe.db.get_value("Account", {"company": company, "root_type": "Expense"})
        
    if not frappe.db.exists("Expense Claim Type", "Travel"):
        try:
            ect = frappe.get_doc({
                "doctype": "Expense Claim Type",
                "name": "Travel",
                "expense_type": "Travel",
                "description": "Travel expenses"
            })
            if expense_account:
                ect.append("accounts", {
                    "company": company,
                    "default_account": expense_account
                })
            ect.insert(ignore_permissions=True)
            print("Created 'Travel' Expense Claim Type.")
        except Exception as e:
            print(f"Warning: Could not create 'Travel' Expense Claim Type: {e}")
    else:
        ect = frappe.get_doc("Expense Claim Type", "Travel")
        has_account = any(a.company == company for a in ect.accounts)
        if not has_account and expense_account:
            ect.append("accounts", {
                "company": company,
                "default_account": expense_account
            })
            ect.save(ignore_permissions=True)
            frappe.db.commit()
        print("'Travel' Expense Claim Type already exists and updated with account.")

    # 4 & 5 & 6. Create 2 NetraNext Journeys — both should land on ONE Draft claim
    created_journeys = []
    for i in range(2):
        print(f"\n--- Creating Journey {i+1}/2 ---")
        journey = frappe.get_doc({
            "doctype": "NetraNext Journey",
            "employee": employee,
            "journey_name": f"Test automated expense journey {i+1}",
            "status": "In Progress",
            "distance_km": 15.5 + i
        })
        journey.insert(ignore_permissions=True)
        frappe.db.commit()
        print(f"Created Journey: {journey.name} with {journey.distance_km} km")

        journey.status = "Completed"
        journey.save(ignore_permissions=True)
        frappe.db.commit()
        print(f"Marked Journey {journey.name} as Completed. Hook should have triggered.")
        created_journeys.append(journey)

    draft_claims = frappe.get_all(
        "Expense Claim",
        filters={"employee": employee, "docstatus": 0},
        order_by="creation desc",
        fields=["name", "total_claimed_amount", "approval_status", "remark", "expense_approver", "docstatus"],
        limit=10,
    )
    trip_claims = [
        c for c in draft_claims
        if c.remark and "Generated automatically for NetraNext" in (c.remark or "")
        and any(j.name in (c.remark or "") for j in created_journeys)
    ]

    print("\n--- TEST RESULTS ---")
    if not trip_claims:
        print("FAILED: No Draft Expense Claim was found for these journeys.")
    else:
        unique_names = {c.name for c in trip_claims}
        claim = frappe.get_doc("Expense Claim", trip_claims[0].name)
        expected_amount = (15.5 + 16.5) * 5.0
        print(f"Found Draft Expense Claim: {claim.name}")
        print(f"Draft claims for these trips: {len(unique_names)} (Expected: 1)")
        print(f"Expense lines: {len(claim.expenses)} (Expected: 2)")
        print(f"Amount: {claim.total_claimed_amount} (Expected: {expected_amount})")
        print(f"Approval Status: {claim.approval_status} / docstatus={claim.docstatus}")
        print(f"Remark: {claim.remark}")

        if len(unique_names) == 1:
            print("SUCCESS: Existing Draft Expense Claim was reused (no duplicate claims).")
        else:
            print("FAILED: Multiple Draft claims were created for the same employee.")

        if len(claim.expenses) == 2:
            print("SUCCESS: Both trip expenses were added to the same Draft claim.")
        else:
            print("WARNING: Expense line count does not match the two completed trips.")

        if abs(float(claim.total_claimed_amount) - float(expected_amount)) < 0.01:
            print("SUCCESS: Combined amount is calculated correctly (submission totals OK).")
        else:
            print("WARNING: Amount doesn't match expected calculation.")

        # Re-save the first completed trip: must update the same draft, not create another
        first = created_journeys[0]
        first.distance_km = 20.0
        first.save(ignore_permissions=True)
        frappe.db.commit()
        claim.reload()
        expected_updated = (20.0 + 16.5) * 5.0
        if abs(float(claim.total_claimed_amount) - float(expected_updated)) < 0.01 and len(claim.expenses) == 2:
            print("SUCCESS: Re-sync updated the existing Draft instead of creating a new claim.")
        else:
            print(
                f"WARNING: After re-sync amount={claim.total_claimed_amount} "
                f"lines={len(claim.expenses)} (expected {expected_updated} / 2)."
            )
            
    print("\n--- Test Complete ---")
    errors = frappe.get_all("Error Log", filters={"creation": [">", frappe.utils.now_datetime()]}, fields=["error", "method"])
    if errors:
        print("\n--- ERROR LOGS ---")
        for e in errors:
            print(e.error)

def simulate_active_trip():
    import json
    from datetime import datetime
    print("--- Starting simulated active trip ---")
    employee = frappe.db.get_value("Employee", {"status": "Active"})
    if not employee:
        print("Error: No active employee found.")
        return
        
    print(f"Using employee: {employee}")
    
    # Delete any existing In Progress journeys
    existing = frappe.db.get_all("NetraNext Journey", filters={"employee": employee, "status": "In Progress"})
    for j in existing:
        frappe.delete_doc("NetraNext Journey", j.name, force=1)
    
    # Create journey
    journey = frappe.get_doc({
        "doctype": "NetraNext Journey",
        "employee": employee,
        "journey_name": "Simulated Live Trip",
        "status": "In Progress",
        "start_time": datetime.now(),
        "start_latitude": 23.0225,
        "start_longitude": 72.5714,
        "distance_km": 1.2,
        "raw_gps_data": json.dumps([
            {"latitude": 23.0125, "longitude": 72.5614, "timestamp": datetime.now().isoformat() + "Z"},
            {"latitude": 23.0155, "longitude": 72.5644, "timestamp": datetime.now().isoformat() + "Z"},
            {"latitude": 23.0185, "longitude": 72.5674, "timestamp": datetime.now().isoformat() + "Z"},
            {"latitude": 23.0225, "longitude": 72.5714, "timestamp": datetime.now().isoformat() + "Z"}
        ])
    })
    
    journey.insert(ignore_permissions=True)
    frappe.db.commit()
    print(f"SUCCESS: Created active journey: {journey.name}")
