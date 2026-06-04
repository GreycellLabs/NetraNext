"""
NetraNext Dashboard API
Queries local database for dashboard data
"""
import frappe
from datetime import datetime

@frappe.whitelist(allow_guest=True)
def get_dashboard_data(date_from=None, date_to=None, employee_id=None, limit=100,
                     journey_page=1, journey_employee=None, attendance_page=1, attendance_employee=None):
    """
    Fetch dashboard data from local database
    """
    try:
        # Set default date range (today) if not provided
        if not date_from:
            date_from = datetime.now().strftime('%Y-%m-%d')
        if not date_to:
            date_to = datetime.now().strftime('%Y-%m-%d')

        # Get REAL employee count from local Employee database
        try:
            total_employees = frappe.db.count("Employee", {"status": "Active"})
        except Exception:
            total_employees = 0

        # Get REAL new hires this year
        try:
            current_year = datetime.now().year
            new_hires = frappe.db.count("Employee", {
                "status": "Active",
                "date_of_joining": ["like", f"{current_year}%"]
            })
        except Exception:
            new_hires = 0

        # Get REAL present today - count unique employees who checked in today
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            present_count = frappe.db.sql("""
                SELECT COUNT(DISTINCT employee) as count
                FROM `tabEmployee Checkin`
                WHERE DATE(time) = %s
            """, today, as_dict=True)
            present_today = present_count[0].get("count", 0) if present_count else 0
        except Exception as e:
            frappe.log_error(f"Present count error: {e}")
            present_today = 0

        # Get REAL journey records
        journeys = []
        try:
            if frappe.db.exists("DocType", "NetraNext Journey"):
                # Use frappe.db.sql instead of get_all to avoid syntax issues
                journey_sql = """
                    SELECT name, employee, start_time as journey_date, start_time, end_time,
                           start_location, end_location, distance_km as total_distance, status,
                           raw_gps_data
                    FROM `tabNetraNext Journey`
                    WHERE DATE(start_time) >= %s AND DATE(start_time) <= %s
                    ORDER BY creation DESC
                    LIMIT %s
                """

                journey_records = frappe.db.sql(journey_sql, (date_from, date_to, int(limit)), as_dict=True)
                
                import json
                for journey in journey_records:
                    # Get employee name
                    employee_name = journey.employee
                    try:
                        employee_doc = frappe.get_doc("Employee", journey.employee)
                        employee_name = employee_doc.employee_name
                    except Exception:
                        pass

                    raw_coords = []
                    if journey.raw_gps_data:
                        try:
                            raw_coords = json.loads(journey.raw_gps_data)
                        except Exception:
                            pass

                    journeys.append({
                        "name": journey.name,
                        "employee": journey.employee,
                        "employee_name": employee_name,
                        "start_time": str(journey.start_time) if journey.start_time else "",
                        "end_time": str(journey.end_time) if journey.end_time else "",
                        "start_location": journey.start_location or "Unknown",
                        "end_location": journey.end_location or "Unknown",
                        "distance_km": journey.total_distance or 0,
                        "status": journey.status or "Completed",
                        "raw_coordinates": raw_coords
                    })
        except Exception as e:
            frappe.log_error(f"Journey fetch error: {e}")
            pass

        # Get REAL attendance records
        attendance = []
        try:
            attendance_sql = """
                SELECT employee, MIN(time) as first_checkin, MAX(time) as last_checkin
                FROM `tabEmployee Checkin`
                WHERE time >= %s AND time <= %s
                GROUP BY employee
                ORDER BY first_checkin DESC
                LIMIT 5
            """

            attendance_records = frappe.db.sql(attendance_sql,
                (f"{date_from} 00:00:00", f"{date_to} 23:59:59"),
                as_dict=True)

            for att in attendance_records:
                # Get employee name
                employee_name = att.employee
                try:
                    employee_doc = frappe.get_doc("Employee", att.employee)
                    employee_name = employee_doc.employee_name
                except Exception:
                    pass

                # Get detailed logs for this employee
                logs_sql = """
                    SELECT log_type, TIME(time) as log_time
                    FROM `tabEmployee Checkin`
                    WHERE employee = %s AND DATE(time) = %s
                    ORDER BY time ASC
                """

                log_records = frappe.db.sql(logs_sql,
                    (att.employee, str(att.first_checkin).split()[0] if att.first_checkin else date_from),
                    as_dict=True)

                logs = []
                for log in log_records:
                    logs.append({
                        "log_type": log.log_type,
                        "time": str(log.log_time) if log.log_time else "00:00:00"
                    })

                attendance.append({
                    "employee": att.employee,
                    "employee_name": employee_name,
                    "attendance_date": str(att.first_checkin).split()[0] if att.first_checkin else date_from,
                    "logs": logs
                })
        except Exception as e:
            frappe.log_error(f"Attendance fetch error: {e}")
            pass

        # Get all employees for dropdown
        all_employees = []
        try:
            employee_sql = """
                SELECT name, employee_name
                FROM `tabEmployee`
                WHERE status = 'Active'
                ORDER BY employee_name ASC
                LIMIT 50
            """

            employee_records = frappe.db.sql(employee_sql, as_dict=True)

            for emp in employee_records:
                all_employees.append({
                    "name": emp.name,
                    "employee_name": emp.employee_name
                })
        except Exception:
            # If employee query fails, continue with empty list
            pass

        # Build response with REAL data
        has_data = len(journeys) > 0 or len(attendance) > 0 or total_employees > 0

        if not has_data:
            message_text = "No dashboard data available yet. Start by adding employees and marking attendance."
        else:
            message_text = "Dashboard data loaded successfully"

        return {
            "status": "success",
            "message": message_text,
            "data": {
                "journeys": journeys,
                "attendance": attendance,
                "summary": {
                    "total_employees": total_employees,
                    "new_hires_this_year": new_hires,
                    "present_today": present_today
                },
                "all_employees": all_employees,
                "total_journeys": len(journeys),
                "total_attendance": len(attendance)
            }
        }

    except Exception as e:
        frappe.log_error(f"Dashboard API error: {str(e)}")
        return {
            "status": "error",
            "message": f"Error fetching dashboard data: {str(e)}",
            "data": None
        }