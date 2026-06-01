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

    # 4 & 5 & 6. Create 2 NetraNext Journeys and verify
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
    
        # 5. Complete the Journey (this should trigger the expense claim)
        journey.status = "Completed"
        journey.save(ignore_permissions=True)
        frappe.db.commit()
        print(f"Marked Journey {journey.name} as Completed. Hook should have triggered.")
    
        # 6. Verify Expense Claim
        # Look for the most recently created expense claim for this employee
        expense_claims = frappe.get_all(
            "Expense Claim", 
            filters={"employee": employee}, 
            order_by="creation desc", 
            limit=1,
            fields=["name", "total_claimed_amount", "approval_status", "remark", "expense_approver"]
        )
    
        if expense_claims:
            claim = expense_claims[0]
            expected_amount = (15.5 + i) * 5.0
            
            print("\n--- TEST RESULTS ---")
            print(f"Found Expense Claim: {claim.name}")
            print(f"Amount: {claim.total_claimed_amount} (Expected: {expected_amount})")
            print(f"Expense Approver: {claim.expense_approver}")
            print(f"Remark: {claim.remark}")
            
            if claim.remark and journey.name in claim.remark:
                print("SUCCESS: The Expense Claim is properly linked to the Journey!")
            else:
                print("WARNING: The Expense Claim remark doesn't seem to mention the journey name.")
                
            if float(claim.total_claimed_amount) == float(expected_amount):
                print("SUCCESS: Amount is calculated correctly!")
            else:
                print("WARNING: Amount doesn't match expected calculation.")
        else:
            print("\n--- TEST RESULTS ---")
            print("FAILED: No Expense Claim was found for this employee.")
            
    print("\n--- Test Complete ---")
    errors = frappe.get_all("Error Log", filters={"creation": [">", frappe.utils.now_datetime()]}, fields=["error", "method"])
    if errors:
        print("\n--- ERROR LOGS ---")
        for e in errors:
            print(e.error)
