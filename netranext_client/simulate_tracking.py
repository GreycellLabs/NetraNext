import frappe
import json
import time
import random
from datetime import datetime
from uuid import uuid4

def execute(duration_minutes=5, interval_seconds=5):
    print("==================================================")
    print(f"STARTING SIMULATION OF 10 DEVICES FOR {duration_minutes} MINUTES")
    print("==================================================")
    
    # 1. Create/Ensure 10 Employees
    employee_ids = []
    for i in range(1, 11):
        emp_id = f"SIM-EMP-{i:02d}"
        emp_name = f"Simulated Driver {i:02d}"
        if not frappe.db.exists("Employee", emp_id):
            emp = frappe.get_doc({
                "doctype": "Employee",
                "employee": emp_id,
                "employee_name": emp_name,
                "first_name": emp_name,
                "status": "Active",
                "company": "brinda tech",
                "personal_email": f"sim_{i}@example.com"
            })
            emp.insert(ignore_permissions=True)
            frappe.db.commit()
        employee_ids.append(emp_id)
        
    # 2. Start "In Progress" Journey for each employee
    # Base location (Ahmedabad center coordinates)
    base_lat, base_lng = 23.0225, 72.5714 
    
    active_journeys = []
    for i, emp_id in enumerate(employee_ids):
        journey_uuid = str(uuid4())
        
        # Start coordinate
        # Offset starting locations slightly for each device so they are spread out
        offset_lat = (i - 5) * 0.004
        offset_lng = (random.random() - 0.5) * 0.01
        start_lat = base_lat + offset_lat
        start_lng = base_lng + offset_lng
        
        gps_points = [
            {"latitude": start_lat, "longitude": start_lng, "timestamp": datetime.utcnow().isoformat() + "Z"}
        ]
        
        journey = frappe.get_doc({
            "doctype": "NetraNext Journey",
            "employee": emp_id,
            "journey_name": f"Simulated Route {i+1}",
            "status": "In Progress",
            "flutter_journey_id": journey_uuid,
            "user_id": f"sim_{i}@example.com",
            "start_time": frappe.utils.now_datetime(),
            "raw_gps_data": json.dumps(gps_points)
        })
        journey.insert(ignore_permissions=True)
        frappe.db.commit()
        
        active_journeys.append({
            "doc": journey,
            "current_lat": start_lat,
            "current_lng": start_lng,
            "points": gps_points,
            # Random direction vectors for moving
            "dir_lat": random.choice([-1, 1]) * random.uniform(0.0001, 0.0003),
            "dir_lng": random.choice([-1, 1]) * random.uniform(0.0001, 0.0003)
        })
        
    # 3. Simulate movement loop
    start_time = time.time()
    end_time = start_time + (duration_minutes * 60)
    
    print("\nSimulation running! Go to your browser and reload the 'Live Tracking' page.")
    print("Press Ctrl+C in this terminal to stop early.\n")
    
    try:
        while time.time() < end_time:
            time.sleep(interval_seconds)
            
            for item in active_journeys:
                # Update location with small movement
                item["current_lat"] += item["dir_lat"]
                item["current_lng"] += item["dir_lng"]
                
                new_point = {
                    "latitude": item["current_lat"],
                    "longitude": item["current_lng"],
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }
                item["points"].append(new_point)
                
                # Update document
                journey_doc = frappe.get_doc("NetraNext Journey", item["doc"].name)
                journey_doc.raw_gps_data = json.dumps(item["points"])
                journey_doc.save(ignore_permissions=True)
                
            frappe.db.commit()
            print(f"-> Location updated for 10 devices at {datetime.now().strftime('%H:%M:%S')}")
            
    except KeyboardInterrupt:
        print("\nSimulation stopped manually.")
    finally:
        # 4. Clean up: Complete journeys so they don't stay active forever
        print("\nCleaning up: Marking simulated journeys as Completed...")
        for item in active_journeys:
            journey_doc = frappe.get_doc("NetraNext Journey", item["doc"].name)
            journey_doc.status = "Completed"
            journey_doc.end_time = frappe.utils.now_datetime()
            journey_doc.save(ignore_permissions=True)
        frappe.db.commit()
        print("Cleanup completed successfully.")
