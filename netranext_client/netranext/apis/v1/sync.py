"""
Tenant Bench Sync API endpoints for NetraNext SaaS integration

This module provides sync endpoints that allow the central NetraNext server
to communicate with tenant benches for:
- Employee data retrieval
- Face embedding synchronization
- Attendance record storage
- Journey data storage
- Face registration storage
"""
import frappe
from frappe import _
import json
from datetime import datetime
from netranext_client.netranext.utils.response_formatter import create_success_response, create_error_response
from netranext_client.netranext.utils.logger import tenant_bench_logger
from netranext_client.netranext.utils.error_handler import handle_api_exception, AuthenticationException, ValidationException, ResourceNotFoundException
from netranext_client.netranext.utils.validators import validate_required_fields, validate_employee_exists


def validate_sync_request():
    """
    Validate that the request comes from a legitimate central server
    Checks Integration Token from request headers
    """
    if not hasattr(frappe, "local") or not getattr(frappe.local, "request", None):
        return True

    incoming_token = frappe.get_request_header("X-NetraNext-Token")

    if not incoming_token:
        tenant_bench_logger.warning("Sync request without Integration Token", "SYNC_VALIDATION")
        raise AuthenticationException("Missing Integration Token. Please provide X-NetraNext-Token header.")

    # Get stored token
    settings = frappe.get_single("NetraNext Settings")
    stored_token = settings.get_password("api_key")

    if not stored_token or incoming_token != stored_token:
        tenant_bench_logger.warning(f"Sync request with invalid Integration Token. Incoming: '{incoming_token}', Stored: '{stored_token}'", "SYNC_VALIDATION")
        raise AuthenticationException("Invalid Integration Token")

    tenant_bench_logger.debug("Sync request validated successfully", "SYNC_VALIDATION")
    return True


@frappe.whitelist(allow_guest=True)
def get_employee_data(employee_id=None, user_id=None):
    """
    Get employee data from tenant bench
    Called by central server to fetch employee information

    Args:
        employee_id: Employee ID (optional)
        user_id: User ID linked to employee (optional)

    Returns:
        dict: Employee data with status
    """
    try:
        # Validate sync request
        validate_sync_request()

        if not employee_id and not user_id:
            raise ValidationException("Either employee_id or user_id is required")

        # Build filters
        filters = {}
        if employee_id:
            filters["name"] = employee_id
        if user_id:
            filters["user_id"] = user_id

        # Get employee data
        employees = frappe.get_all(
            "Employee",
            filters=filters,
            fields=[
                "name",
                "employee_name",
                "employee",
                "user_id",
                "department",
                "designation",
                "branch",
                "company",
                "image",
                "attendance_device_id",
                "status"
            ],
            limit=1
        )

        if not employees:
            raise ResourceNotFoundException("Employee")

        employee_data = employees[0]

        # Add additional employee details
        employee_doc = frappe.get_doc("Employee", employee_data["name"])

        # Add employment details
        employee_data["date_of_joining"] = str(employee_doc.date_of_joining) if employee_doc.date_of_joining else None
        employee_data["employment_type"] = getattr(employee_doc, 'employment_type', None)
        employee_data["reports_to"] = getattr(employee_doc, 'reports_to', None)

        # Add contact information if available
        employee_data["cell_number"] = getattr(employee_doc, 'cell_number', None)
        employee_data["personal_email"] = getattr(employee_doc, 'personal_email', None)
        employee_data["company_email"] = getattr(employee_doc, 'company_email', None)

        tenant_bench_logger.info(f"Employee data retrieved: {employee_data['name']}", "EMPLOYEE_SYNC")

        return create_success_response(
            message="Employee data retrieved successfully",
            data=employee_data
        )

    except Exception as e:
        return handle_api_exception(e, "EMPLOYEE_SYNC")


@frappe.whitelist(allow_guest=True)
def get_employee_faces(employee_id=None):
    """
    Get registered face embeddings for employee(s)
    Called by central server for face recognition processing

    Args:
        employee_id: Specific employee ID (optional, if not provided returns all)

    Returns:
        dict: Employee face data with embeddings
    """
    try:
        # Validate sync request
        validate_sync_request()

        # Check if NetraNext Face Registration DocType exists on tenant bench
        # If not, return empty response
        if not frappe.db.exists("DocType", "NetraNext Face Registration"):
            return create_success_response(
                message="Face registration not available on this tenant bench",
                data={"faces": []}
            )

        # Build filters
        filters = {}
        if employee_id:
            filters["employee"] = employee_id

        # Get face registrations
        face_regs = frappe.get_all(
            "NetraNext Face Registration",
            filters=filters,
            fields=[
                "name",
                "employee",
                "face_id",
                "face_embedding",
                "face_photo",
                "registered_date"
            ]
        )

        faces = []
        for face_reg in face_regs:
            try:
                # Parse embedding JSON
                embedding = json.loads(face_reg.face_embedding) if face_reg.face_embedding else []

                face_data = {
                    "face_id": face_reg.face_id,
                    "employee_id": face_reg.employee,
                    "embedding": embedding,
                    "face_photo_url": face_reg.face_photo,
                    "registered_date": face_reg.registered_date.isoformat() if face_reg.registered_date else None
                }
                faces.append(face_data)
            except Exception as e:
                tenant_bench_logger.error(f"Error parsing face data for {face_reg.name}: {str(e)}", "FACE_SYNC")
                continue

        tenant_bench_logger.info(f"Retrieved {len(faces)} face registration(s)", "FACE_SYNC")

        return create_success_response(
            message=f"Retrieved {len(faces)} face registration(s)",
            data={"faces": faces}
        )

    except Exception as e:
        return handle_api_exception(e, "FACE_SYNC")


@frappe.whitelist(allow_guest=True)
def store_attendance(att_data):
    """
    Store attendance record from central server
    Creates Employee Checkin record on tenant bench

    Args:
        att_data: Attendance data dict with employee, time, location, etc.

    Returns:
        dict: Storage result
    """
    try:
        # Validate sync request
        validate_sync_request()

        # Parse attendance data
        if isinstance(att_data, str):
            att_data = json.loads(att_data)

        # Validate required fields
        validate_required_fields(att_data, ["employee_id", "time", "log_type"])

        # Check if employee exists
        validate_employee_exists(att_data["employee_id"])

        # Prevent duplicate check-in/checkout log for the same employee within 2 minutes of the same timestamp
        from frappe.utils import get_datetime
        from datetime import timedelta

        checkin_time = get_datetime(att_data["time"])
        time_threshold_start = checkin_time - timedelta(minutes=2)
        time_threshold_end = checkin_time + timedelta(minutes=2)

        if frappe.db.exists("Employee Checkin", {
            "employee": att_data["employee_id"],
            "log_type": att_data["log_type"],
            "time": ["between", [time_threshold_start, time_threshold_end]],
        }):
            employee_name = frappe.db.get_value("Employee", att_data["employee_id"], "employee_name") or att_data["employee_id"]
            tenant_bench_logger.info(
                f"Skipped duplicate attendance for {att_data['employee_id']} ({att_data['log_type']}) - already exists within 2 minutes",
                "ATTENDANCE_SYNC"
            )
            return create_success_response(
                message=f"{employee_name} is already checked in",
                data={
                    "already_checked_in": True,
                    "checkin_id": None,
                    "employee": att_data["employee_id"],
                    "log_type": att_data["log_type"]
                }
            )

        # Download photo from orchestrator and save locally on client bench
        local_photo_url = att_data.get("photo_proof")
        remote_photo_url = att_data.get("photo_proof")
        if remote_photo_url:
            try:
                import requests
                from frappe.utils.file_manager import save_file
                import os

                response = requests.get(remote_photo_url, timeout=15)
                if response.status_code == 200:
                    filename = os.path.basename(remote_photo_url.split("?")[0])
                    file_doc = save_file(
                        fname=filename,
                        content=response.content,
                        dt=None,
                        dn=None,
                        is_private=0
                    )
                    if file_doc:
                        local_photo_url = file_doc.file_url
                        tenant_bench_logger.info(f"Photo saved locally: {local_photo_url}", "ATTENDANCE_SYNC")
            except Exception as photo_err:
                tenant_bench_logger.warning(f"Could not download photo, using remote URL: {str(photo_err)}", "ATTENDANCE_SYNC")

        # Create Employee Checkin record
        latitude = att_data.get("latitude")
        longitude = att_data.get("longitude")
        if latitude is not None:
            try:
                latitude = float(latitude)
            except (ValueError, TypeError):
                latitude = None
        if longitude is not None:
            try:
                longitude = float(longitude)
            except (ValueError, TypeError):
                longitude = None

        employee_id = att_data["employee_id"]

        # Fetch employee's assigned locations from custom_assigned_locations child table
        assigned_locations = frappe.get_all("NetraNext Employee Location", filters={
            "parent": employee_id,
            "parenttype": "Employee",
            "parentfield": "custom_assigned_locations"
        }, fields=["location", "latitude", "longitude", "radius_meters", "location_name"])

        in_geofence = True
        if assigned_locations:
            in_geofence = False
            if latitude is not None and longitude is not None:
                import math
                for loc in assigned_locations:
                    if loc.latitude is not None and loc.longitude is not None:
                        # Haversine distance formula
                        R = 6371000.0
                        lat1, lon1 = latitude, longitude
                        lat2, lon2 = float(loc.latitude), float(loc.longitude)
                        
                        phi1 = math.radians(lat1)
                        phi2 = math.radians(lat2)
                        delta_phi = math.radians(lat2 - lat1)
                        delta_lambda = math.radians(lon2 - lon1)
                        
                        a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
                        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
                        dist = R * c
                        
                        radius = loc.radius_meters or 100
                        if dist <= radius:
                            in_geofence = True
                            break

        face_status = att_data.get("custom_face_status", "Approved")
        face_failure_reason = att_data.get("custom_face_failure_reason")

        checkin_doc = frappe.get_doc({
            "doctype": "Employee Checkin",
            "employee": employee_id,
            "time": att_data["time"],
            "log_type": att_data["log_type"],
            "device_id": att_data.get("device_id", "NetraNext"),
            "latitude": latitude,
            "longitude": longitude,
            "location_address": att_data.get("location_address"),
            "photo_proof": local_photo_url,
            "skip_auto_attendance": 0 if (in_geofence and face_status == "Approved") else 1,
            "custom_location_status": "Approved" if in_geofence else "Pending Approval",
            "custom_face_status": face_status,
            "custom_face_failure_reason": face_failure_reason
        })

        checkin_doc.insert(ignore_permissions=True)

        # If outside geofence, create approval request
        if not in_geofence:
            try:
                approval_doc = frappe.get_doc({
                    "doctype": "NetraNext Location Checkin Approval",
                    "employee": employee_id,
                    "employee_checkin": checkin_doc.name,
                    "log_type": att_data["log_type"],
                    "time": att_data["time"],
                    "latitude": latitude or 0.0,
                    "longitude": longitude or 0.0,
                    "location_address": att_data.get("location_address"),
                    "status": "Pending"
                })
                approval_doc.insert(ignore_permissions=True)
            except Exception as approval_err:
                tenant_bench_logger.error(f"Failed to create Location Checkin Approval: {str(approval_err)}", "ATTENDANCE_SYNC")

        # If face recognition is pending approval, create face approval request
        if face_status == "Pending Approval":
            try:
                face_approval_doc = frappe.get_doc({
                    "doctype": "NetraNext Face Checkin Approval",
                    "employee": employee_id,
                    "employee_checkin": checkin_doc.name,
                    "log_type": att_data["log_type"],
                    "time": att_data["time"],
                    "failure_reason": face_failure_reason or "Match Failure",
                    "photo_proof": local_photo_url,
                    "status": "Pending"
                })
                face_approval_doc.insert(ignore_permissions=True)
            except Exception as face_approval_err:
                tenant_bench_logger.error(f"Failed to create Face Checkin Approval: {str(face_approval_err)}", "ATTENDANCE_SYNC")

        tenant_bench_logger.info(f"Attendance stored for employee {att_data['employee_id']}", "ATTENDANCE_SYNC")

        return create_success_response(
            message="Attendance record stored successfully",
            data={
                "checkin_id": checkin_doc.name,
                "employee": att_data["employee_id"],
                "time": att_data["time"],
                "log_type": att_data["log_type"]
            }
        )

    except Exception as e:
        return handle_api_exception(e, "ATTENDANCE_SYNC")


@frappe.whitelist(allow_guest=True)
def store_face(face_data):
    """
    Store face registration from central server
    Updates Employee attendance_device_id on tenant bench

    Args:
        face_data: Face registration dict with employee, embedding, photo, etc.

    Returns:
        dict: Storage result
    """
    try:
        # Validate sync request
        validate_sync_request()

        # Parse face data
        if isinstance(face_data, str):
            face_data = json.loads(face_data)

        # Validate required fields
        validate_required_fields(face_data, ["employee_id", "face_id"])

        # Check if employee exists
        validate_employee_exists(face_data["employee_id"])

        # Update employee attendance_device_id
        frappe.db.set_value(
            "Employee",
            face_data["employee_id"],
            "attendance_device_id",
            face_data["face_id"]
        )

        tenant_bench_logger.info(f"Face registration synced successfully for employee {face_data['employee_id']}", "FACE_SYNC")

        return create_success_response(
            message="Face registration synced successfully",
            data={
                "face_id": face_data["face_id"],
                "employee_id": face_data["employee_id"],
                "action": "synced"
            }
        )

    except Exception as e:
        return handle_api_exception(e, "FACE_SYNC")


@frappe.whitelist(allow_guest=True)
def store_journey(journey_data):
    """
    Store GPS journey from central server
    Creates NetraNext Journey record on tenant bench

    Args:
        journey_data: Journey data dict with employee, route, coordinates, etc.

    Returns:
        dict: Storage result
    """
    try:
        # Validate sync request
        validate_sync_request()

        # Parse journey data
        if isinstance(journey_data, str):
            journey_data = json.loads(journey_data)

        # Validate required fields
        if not journey_data.get("employee_id"):
            raise ValidationException("employee_id is required")

        # Check if employee exists
        validate_employee_exists(journey_data["employee_id"])

        # Check if NetraNext Journey DocType exists
        if not frappe.db.exists("DocType", "NetraNext Journey"):
            raise ResourceNotFoundException("NetraNext Journey DocType")

        # Derive journey_date from start_time if not provided
        start_time_raw = journey_data.get("start_time")
        end_time_raw = journey_data.get("end_time")

        journey_date = journey_data.get("journey_date")
        if not journey_date and start_time_raw:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(start_time_raw.replace("Z", "+00:00"))
                journey_date = dt.strftime("%Y-%m-%d")
            except Exception:
                journey_date = frappe.utils.today()

        if not journey_date:
            journey_date = frappe.utils.today()

        # Build the doc — handle both old and new field schemas gracefully
        doc_data = {
            "doctype": "NetraNext Journey",
            "employee": journey_data["employee_id"],
            "journey_date": journey_date,
            "start_time": start_time_raw,
            "end_time": end_time_raw,
            "start_location": journey_data.get("start_location"),
            "end_location": journey_data.get("end_location"),
            "status": journey_data.get("status", "Completed"),
        }

        # Optional fields — set only if the field exists in the DocType
        journey_meta = frappe.get_meta("NetraNext Journey")
        field_names = [f.fieldname for f in journey_meta.fields]

        optional_mappings = {
            "journey_name": journey_data.get("journey_name"),
            "flutter_journey_id": journey_data.get("journey_id"),
            "user_id": journey_data.get("user_id"),
            "distance_km": journey_data.get("distance_km"),
            "total_distance": journey_data.get("distance_km"),
            "duration_seconds": journey_data.get("duration_seconds"),
            "encoded_polyline": journey_data.get("encoded_polyline"),
            "optimized_polyline": journey_data.get("encoded_polyline"),
            "original_points_count": journey_data.get("original_points_count"),
            "simplified_points_count": journey_data.get("simplified_points_count"),
            "waypoint_count": journey_data.get("original_points_count"),
            "metadata": journey_data.get("metadata"),
            "raw_gps_data": journey_data.get("raw_gps_data"),
            "raw_coordinates": journey_data.get("raw_gps_data"),
            "scheduled_start_time": journey_data.get("scheduled_start_time"),
            "scheduled_end_time": journey_data.get("scheduled_end_time"),
            "destination_address": journey_data.get("destination_address"),
        }

        for field, value in optional_mappings.items():
            if field in field_names and value is not None:
                doc_data[field] = value

        flutter_journey_id = journey_data.get("journey_id")
        trip_id = journey_data.get("trip_id")

        # Check if journey already exists from the same Flutter session (with cache lock to prevent concurrent double-inserts)
        # Match on employee as well: different users may start the same scheduled trip
        # under the same flutter_journey_id, and each must keep their own journey record
        # so one user's connectivity does not affect another's tracking data/online status.
        journey_filters = {
            "flutter_journey_id": flutter_journey_id,
            "employee": journey_data["employee_id"],
        }
        existing_journey = None
        if flutter_journey_id:
            lock_key = f"lock_journey_{flutter_journey_id}_{journey_data['employee_id']}"
            if frappe.cache().get_value(lock_key):
                # A request for this journey is already running. Wait for it to commit.
                import time
                for _ in range(10):
                    time.sleep(0.3)
                    existing_journey = frappe.db.get_value("NetraNext Journey", journey_filters, "name")
                    if existing_journey:
                        break
            else:
                frappe.cache().set_value(lock_key, "1", expires_in_sec=15)

            if not existing_journey:
                existing_journey = frappe.db.get_value("NetraNext Journey", journey_filters, "name")
            
        if existing_journey:
            # Update the existing journey (e.g., transition from In Progress -> Completed)
            journey_doc = frappe.get_doc("NetraNext Journey", existing_journey)
            for field, value in doc_data.items():
                if field != "doctype" and value is not None:
                    journey_doc.set(field, value)
            journey_doc.save(ignore_permissions=True)
            action = "updated"
        else:
            # Create a new Journey for the tracked route
            journey_doc = frappe.get_doc(doc_data)
            journey_doc.insert(ignore_permissions=True)
            action = "stored"

        # If this journey is "In Progress", ensure no other journeys for this employee are "In Progress"
        if doc_data.get("status") == "In Progress":
            frappe.db.sql("""
                UPDATE `tabNetraNext Journey`
                SET status = 'Completed', end_time = %s
                WHERE employee = %s AND status = 'In Progress' AND name != %s
            """, (frappe.utils.now_datetime(), doc_data["employee"], journey_doc.name))
        
        tenant_bench_logger.info(f"Checking Scheduled Trip. Received trip_id: {trip_id}", "JOURNEY_SYNC")
        
        # If this journey is fulfilling a Scheduled Trip, update its status
        if trip_id and frappe.db.exists("Scheduled Trip", trip_id):
            scheduled_trip = frappe.get_doc("Scheduled Trip", trip_id)
            tenant_bench_logger.info(f"Found Scheduled Trip {trip_id} with current status {scheduled_trip.status}. Setting to {doc_data.get('status')}", "JOURNEY_SYNC")
            
            if doc_data.get("status") == "Completed":
                scheduled_trip.status = "Completed"
                scheduled_trip.journey_reference = journey_doc.name
                scheduled_trip.save(ignore_permissions=True)
                tenant_bench_logger.info(f"Scheduled Trip {trip_id} status updated to Completed", "JOURNEY_SYNC")
            elif doc_data.get("status") == "In Progress":
                scheduled_trip.status = "In Progress"
                scheduled_trip.journey_reference = journey_doc.name
                scheduled_trip.save(ignore_permissions=True)
                tenant_bench_logger.info(f"Scheduled Trip {trip_id} status updated to In Progress", "JOURNEY_SYNC")
        else:
            if trip_id:
                tenant_bench_logger.error(f"Scheduled Trip {trip_id} does not exist!", "JOURNEY_SYNC")

        tenant_bench_logger.info(f"Journey {action} for employee {journey_data['employee_id']}: {journey_doc.name}", "JOURNEY_SYNC")

        return create_success_response(
            message="Journey stored successfully",
            data={
                "journey_id": journey_doc.name,
                "journey_name": journey_doc.name,
                "employee_id": journey_data["employee_id"],
                "journey_date": journey_date,
                "start_time": start_time_raw,
                "end_time": end_time_raw
            }
        )

    except Exception as e:
        return handle_api_exception(e, "JOURNEY_SYNC")


@frappe.whitelist(allow_guest=True)
def update_employee_device_id(employee_id=None, attendance_device_id=None):
    """
    Update employee attendance_device_id
    Called by central server after face registration

    Args:
        employee_id: Employee ID
        attendance_device_id: Device ID (face_id)

    Returns:
        dict: Update result
    """
    try:
        # Validate sync request
        validate_sync_request()

        if not employee_id or not attendance_device_id:
            raise ValidationException("employee_id and attendance_device_id are required")

        # Check if employee exists
        validate_employee_exists(employee_id)

        # Update employee
        frappe.db.set_value(
            "Employee",
            employee_id,
            "attendance_device_id",
            attendance_device_id
        )

        tenant_bench_logger.info(f"Updated device ID for employee {employee_id}", "EMPLOYEE_SYNC")

        return create_success_response(
            message="Employee updated successfully",
            data={
                "employee_id": employee_id,
                "attendance_device_id": attendance_device_id
            }
        )

    except Exception as e:
        return handle_api_exception(e, "EMPLOYEE_SYNC")


@frappe.whitelist(allow_guest=True)
def authenticate_user(email=None, password=None):
    """
    Authenticate user against tenant bench
    Called by central server to validate user credentials for specific tenant

    Args:
        email: User email
        password: User password

    Returns:
        dict: Authentication result with user and employee data
    """
    try:
        # Validate sync request
        validate_sync_request()

        # Validate required fields
        if not email or not password:
            raise ValidationException("Email and password are required")

        # Authenticate using Frappe's LoginManager with fallback
        from frappe.auth import LoginManager
        from frappe.utils.password import check_password

        tenant_bench_logger.info(f"Attempting authentication for {email}", "TENANT_AUTH")

        try:
            # Try standard LoginManager first
            login_manager = LoginManager()
            login_manager.authenticate(user=email, pwd=password)
            login_manager.post_login()
            user = frappe.session.user
            tenant_bench_logger.info(f"LoginManager authentication successful for {user}", "TENANT_AUTH")
        except (AttributeError, KeyError) as e:
            # Fallback to check_password when request context is missing
            tenant_bench_logger.info(f"LoginManager failed with {type(e).__name__}, using check_password fallback", "TENANT_AUTH")
            user = check_password(email, password)
            if not user:
                tenant_bench_logger.warning(f"check_password returned None for {email}", "TENANT_AUTH")
                raise frappe.AuthenticationError("Invalid email or password")
            tenant_bench_logger.info(f"check_password authentication successful for {user}", "TENANT_AUTH")

        # Get User document
        user_doc = frappe.get_doc("User", user)

        # Check if user is enabled
        if not user_doc.enabled:
            tenant_bench_logger.warning(f"Disabled user attempted login: {user}", "TENANT_AUTH")
            raise AuthenticationException("User account is disabled")

        # Get employee data linked to this user
        employee_data = None
        employees = frappe.get_all(
            "Employee",
            filters={"user_id": user},
            fields=[
                "name",
                "employee_name",
                "user_id",
                "department",
                "designation",
                "branch",
                "company",
                "image",
                "attendance_device_id",
                "status"
            ],
            limit=1
        )

        if employees:
            employee_data = employees[0]
            employee_id = employee_data["name"]
            tenant_bench_logger.info(f"Employee found for user {user}: {employee_id}", "TENANT_AUTH")
        else:
            employee_id = None
            tenant_bench_logger.warning(f"No employee found for user {user}", "TENANT_AUTH")

        # Get custom business logo if configured
        business_logo = frappe.db.get_single_value("NetraNext Settings", "business_logo")
        if business_logo and business_logo.startswith("/"):
            business_logo = frappe.utils.get_url(business_logo)

        # Build response data
        response_data = {
            "user": user,
            "full_name": user_doc.full_name,
            "email": user_doc.email,
            "user_type": user_doc.user_type,
            "enabled": user_doc.enabled,
            "employee_id": employee_id,
            "employee_data": employee_data,
            "business_logo": business_logo or None
        }

        tenant_bench_logger.info(f"User {user} authenticated successfully", "TENANT_AUTH")

        return create_success_response(
            message="Authentication successful",
            data=response_data
        )

    except frappe.AuthenticationError as e:
        tenant_bench_logger.warning(f"Failed authentication attempt for {email}", "TENANT_AUTH")
        return create_error_response("Invalid email or password")

    except Exception as e:
        return handle_api_exception(e, "TENANT_AUTH")


@frappe.whitelist(allow_guest=True)
def health_check():
    """
    Health check endpoint for tenant bench
    Returns basic information about the tenant bench status

    Returns:
        dict: Health status with system information
    """
    try:
        # No authentication required for health check
        return create_success_response(
            message="Tenant bench is healthy",
            data={
                "status": "healthy",
                "bench_type": "tenant",
                "app_version": "netranext_client",
                "timestamp": datetime.now().isoformat(),
                "features": {
                    "employee_management": True,
                    "face_registration": frappe.db.exists("DocType", "NetraNext Face Registration"),
                    "journey_tracking": frappe.db.exists("DocType", "NetraNext Journey"),
                    "attendance_storage": True
                }
            }
        )

    except Exception as e:
        return create_error_response(
            message=f"Health check failed: {str(e)}"
        )


@frappe.whitelist(allow_guest=True)
def get_employee_checkins(employee_id=None, from_date=None, to_date=None, limit=100):
    """
    Get Employee Checkin records for a given employee from the tenant bench.

    Args:
        employee_id (str): Employee ID
        from_date (str): Start datetime filter (optional)
        to_date (str): End datetime filter (optional)
        limit (int): Max records to return (default 100)

    Returns:
        dict: Checkin records
    """
    try:
        validate_sync_request()

        if not employee_id:
            raise ValidationException("employee_id is required")

        validate_employee_exists(employee_id)

        filters = [["employee", "=", employee_id]]
        if from_date:
            filters.append(["time", ">=", from_date])
        if to_date:
            filters.append(["time", "<=", to_date])

        checkins = frappe.get_all(
            "Employee Checkin",
            filters=filters,
            fields=[
                "name", "employee", "log_type", "time",
                "device_id", "latitude", "longitude",
                "location_address", "photo_proof", "creation", "modified",
                "custom_face_status", "custom_location_status"
            ],
            order_by="time asc",
            limit=int(limit),
            ignore_permissions=True
        )

        # Serialize datetime fields
        for c in checkins:
            for field in ["time", "creation", "modified"]:
                if c.get(field):
                    c[field] = str(c[field])

        tenant_bench_logger.info(f"Returned {len(checkins)} checkins for {employee_id}", "CHECKIN_SYNC")

        return create_success_response(
            message=f"Found {len(checkins)} checkin records",
            data={
                "employee_id": employee_id,
                "checkins": checkins,
                "total_count": len(checkins)
            }
        )

    except Exception as e:
        return handle_api_exception(e, "CHECKIN_SYNC")


@frappe.whitelist(allow_guest=True)
def get_journeys(employee_id=None, user_id=None, limit=50, status=None):
    """
    Get NetraNext Journey records from the tenant bench.

    Args:
        employee_id (str): Employee ID filter
        user_id (str): User ID filter
        limit (int): Max records (default 50)
        status (str): Status filter

    Returns:
        dict: Journey records
    """
    try:
        validate_sync_request()

        # Fetch Scheduled Trips from ToDo for today
        scheduled_trips = []
        if frappe.db.exists("DocType", "Scheduled Trip"):
            todo_user_id = user_id
            if not todo_user_id and employee_id:
                todo_user_id = frappe.db.get_value("Employee", employee_id, "user_id")
            
            if todo_user_id:
                todo_filters = {
                    "reference_type": "Scheduled Trip",
                    "allocated_to": todo_user_id,
                    "date": frappe.utils.today(),
                    "status": "Open"
                }
                
                todos = frappe.get_all(
                    "ToDo",
                    filters=todo_filters,
                    fields=["reference_name"],
                    ignore_permissions=True
                )
                
                trip_names = [t.reference_name for t in todos if t.reference_name]
                
                if trip_names:
                    scheduled_filters = [["name", "in", trip_names]]
                    if status:
                        scheduled_filters.append(["status", "=", status])
                        
                    scheduled_trips = frappe.get_all(
                        "Scheduled Trip",
                        filters=scheduled_filters,
                        fields=["name", "employee", "status", "scheduled_start_time", "scheduled_end_time", "destination_address", "creation"],
                        order_by="scheduled_start_time asc",
                        ignore_permissions=True
                    )
        
        # Convert to Flutter format
        journeys = []
        
        # Add scheduled trips
        for s_trip in scheduled_trips:
            journeys.append({
                "id": s_trip.name,
                "tripId": s_trip.name,
                "userId": user_id,
                "status": s_trip.status,
                "scheduledStartTime": str(s_trip.scheduled_start_time) if s_trip.scheduled_start_time else None,
                "scheduledEndTime": str(s_trip.scheduled_end_time) if s_trip.scheduled_end_time else None,
                "destinationAddress": s_trip.destination_address,
                "isActive": False,
                "points": [],
            })

        tenant_bench_logger.info(f"Returned {len(journeys)} journeys", "JOURNEY_SYNC")

        return create_success_response(
            message=f"Found {len(journeys)} journeys",
            data={
                "journeys": journeys,
                "total": len(journeys)
            }
        )

    except Exception as e:
        return handle_api_exception(e, "JOURNEY_SYNC")

@frappe.whitelist(allow_guest=True)
def get_journey_details(trip_id=None, journey_id=None):
    """
    Get journey details from the tenant bench.

    Args:
        trip_id (str): Journey ID/Name
        journey_id (str): Journey UUID from Flutter

    Returns:
        dict: Journey details
    """
    try:
        validate_sync_request()

        if not trip_id and not journey_id:
            return create_error_response("trip_id or journey_id is required")

        if not frappe.db.exists("DocType", "NetraNext Journey"):
            return create_error_response("Journey DocType not found")

        # Find trip
        trip = None
        if trip_id:
            if frappe.db.exists("NetraNext Journey", trip_id):
                trip = frappe.get_doc("NetraNext Journey", trip_id)
        elif journey_id:
            # First check flutter_journey_id field
            journey_meta = frappe.get_meta("NetraNext Journey")
            field_names = [f.fieldname for f in journey_meta.fields]
            
            if "flutter_journey_id" in field_names:
                trips = frappe.get_all("NetraNext Journey", filters={"flutter_journey_id": journey_id}, limit=1)
                if trips:
                    trip = frappe.get_doc("NetraNext Journey", trips[0].name)
            
            # Fallback to search in metadata
            if not trip and "metadata" in field_names:
                all_trips = frappe.get_all("NetraNext Journey", fields=["name", "metadata"])
                for t in all_trips:
                    if t.get("metadata"):
                        import json
                        try:
                            metadata = json.loads(t.metadata) if isinstance(t.metadata, str) else t.metadata
                            if metadata.get("journey_id") == journey_id or metadata.get("flutter_journey_id") == journey_id:
                                trip = frappe.get_doc("NetraNext Journey", t.name)
                                break
                        except:
                            pass

        if not trip:
            return create_error_response("Journey not found")

        # Parse metadata
        metadata = {}
        if trip.get("metadata"):
            import json
            try:
                metadata = json.loads(trip.metadata) if isinstance(trip.metadata, str) else trip.metadata
            except:
                pass

        # Build response - include raw GPS coordinates for full detailed route
        coordinates = []
        raw_gps = trip.get("raw_gps_data") or trip.get("raw_coordinates")
        if raw_gps:
            import json
            try:
                raw_points = json.loads(raw_gps) if isinstance(raw_gps, str) else raw_gps
                coordinates = [[point.get("latitude"), point.get("longitude")] for point in raw_points if point.get("latitude") and point.get("longitude")]
            except Exception as e:
                tenant_bench_logger.warning(f"Failed to parse raw GPS data: {str(e)}", "JOURNEY_SYNC")

        response_data = {
            "trip_id": trip.name,
            "journey_id": trip.get("flutter_journey_id") or metadata.get("journey_id"),
            "user_id": trip.get("user_id") or metadata.get("user_id"),
            "employee_id": trip.employee,
            "journey_name": trip.get("journey_name"),
            "status": trip.status,
            "start_time": trip.get("start_time"),
            "end_time": trip.get("end_time"),
            "start_address": trip.get("start_location") or metadata.get("start_address", ""),
            "end_address": trip.get("end_location") or metadata.get("end_address", ""),
            "distance_km": trip.get("distance_km") or trip.get("total_distance"),
            "duration_seconds": trip.get("duration_seconds") or 0,
            "encoded_polyline": trip.get("encoded_polyline") or trip.get("optimized_polyline"),
            "coordinates": coordinates,
            "points_count": trip.get("original_points_count") or trip.get("waypoint_count") or 0,
            "simplified_points": trip.get("simplified_points_count") or 0,
            "is_active": trip.status == "In Progress"
        }

        return create_success_response(
            message="Journey retrieved successfully",
            data=response_data
        )

    except Exception as e:
        return handle_api_exception(e, "JOURNEY_SYNC")


@frappe.whitelist(allow_guest=True)
def delete_journey(trip_id=None, journey_id=None):
    """
    Delete a journey from the tenant bench.

    Args:
        trip_id (str): Journey ID/Name
        journey_id (str): Journey UUID from Flutter

    Returns:
        dict: Response with deletion status
    """
    try:
        validate_sync_request()

        if not trip_id and not journey_id:
            return create_error_response("trip_id or journey_id is required")

        if not frappe.db.exists("DocType", "NetraNext Journey"):
            return create_error_response("Journey DocType not found")

        # Find trip
        target_trip_id = trip_id
        if not target_trip_id and journey_id:
            # First check flutter_journey_id field
            journey_meta = frappe.get_meta("NetraNext Journey")
            field_names = [f.fieldname for f in journey_meta.fields]
            
            if "flutter_journey_id" in field_names:
                trips = frappe.get_all("NetraNext Journey", filters={"flutter_journey_id": journey_id}, limit=1)
                if trips:
                    target_trip_id = trips[0].name
            
            # Fallback to metadata search
            if not target_trip_id and "metadata" in field_names:
                all_trips = frappe.get_all("NetraNext Journey", fields=["name", "metadata"])
                for t in all_trips:
                    if t.get("metadata"):
                        import json
                        try:
                            metadata = json.loads(t.metadata) if isinstance(t.metadata, str) else t.metadata
                            if metadata.get("journey_id") == journey_id or metadata.get("flutter_journey_id") == journey_id:
                                target_trip_id = t.name
                                break
                        except:
                            pass

        if not target_trip_id or not frappe.db.exists("NetraNext Journey", target_trip_id):
            return create_error_response("Journey not found")

        # Delete trip
        frappe.delete_doc("NetraNext Journey", target_trip_id, ignore_permissions=True)
        frappe.db.commit()

        return create_success_response(
            message="Journey deleted successfully",
            data={"trip_id": target_trip_id}
        )

    except Exception as e:
        frappe.db.rollback()
        return handle_api_exception(e, "JOURNEY_SYNC")


@frappe.whitelist(allow_guest=True)
def update_tenant_status(status):
    """
    Update tenant connection status in NetraNext Settings.
    Called by central orchestrator when status changes.
    """
    try:
        # Validate sync request
        validate_sync_request()

        # Check if status option is valid
        valid_statuses = ["Active", "Inactive", "Suspended"]
        if status not in valid_statuses:
            return create_error_response(
                message=f"Invalid status value. Must be one of {valid_statuses}",
                status_code=400
            )

        # Get settings and update status using db_set to prevent hooks loop
        settings = frappe.get_single("NetraNext Settings")
        if settings.status != status:
            settings.db_set("status", status)
            frappe.db.commit()

        tenant_bench_logger.info(f"Tenant status updated from orchestrator to: {status}", "STATUS_SYNC")

        return create_success_response(
            message="Tenant status updated successfully",
            data={
                "status": status
            }
        )

    except Exception as e:
        return handle_api_exception(e, "STATUS_SYNC")


@frappe.whitelist(allow_guest=True)
def store_face_registration_request():
    """
    Store a pending face registration/update request on the client bench.
    Called by central orchestrator when a user submits a face registration/update.
    """
    try:
        # Validate sync request
        validate_sync_request()

        data = frappe.request.get_json() or {}

        # Validate required fields
        required = ["employee_id", "face_id", "face_photo_url", "embedding"]
        for field in required:
            if not data.get(field):
                return create_error_response(
                    message=f"Missing required parameter: {field}",
                    status_code=400
                )

        # Check for existing pending request
        existing = frappe.db.exists(
            "NetraNext Face Registration Request",
            {"employee": data.get("employee_id"), "status": "Pending"}
        )
        if existing:
            return create_error_response(
                message=f"There is already a pending face registration request for this employee.",
                status_code=400
            )

        # Create request document
        req = frappe.get_doc({
            "doctype": "NetraNext Face Registration Request",
            "employee": data.get("employee_id"),
            "face_id": data.get("face_id"),
            "request_type": data.get("request_type", "Register"),
            "status": "Pending",
            "face_photo": data.get("face_photo_url"),
            "face_embedding": data.get("embedding"),
            "orchestrator_request_name": data.get("orchestrator_request_name", ""),
            "requested_date": data.get("requested_date") or frappe.utils.now_datetime()
        })

        req.insert(ignore_permissions=True)
        frappe.db.commit()

        tenant_bench_logger.info(
            f"Created pending face registration request {req.name} for employee: {req.employee}",
            "FACE_REGISTRATION_REQUEST_SYNC"
        )

        return create_success_response(
            message="Face registration request stored successfully",
            data={
                "request_name": req.name,
                "status": "Pending"
            }
        )

    except Exception as e:
        frappe.db.rollback()
        return handle_api_exception(e, "FACE_REGISTRATION_REQUEST_SYNC")


@frappe.whitelist(allow_guest=True)
def get_all_employees(user_id=None):
    """
    Get all active employees from the tenant bench
    Called by central server to sync contacts directory
    """
    try:
        # Validate sync request
        validate_sync_request()

        filters = {"status": "Active"}
        
        # If user_id is provided, only return employees assigned to this user via ToDo
        if user_id:
            assigned_todos = frappe.get_all(
                "ToDo",
                filters={
                    "allocated_to": user_id,
                    "reference_type": "Employee",
                    "status": "Open"
                },
                pluck="reference_name"
            )
            
            if assigned_todos:
                filters["name"] = ["in", assigned_todos]
            else:
                return create_success_response(
                    message="Active employees retrieved successfully",
                    data=[]
                )

        # Get all active employees
        employees = frappe.get_all(
            "Employee",
            filters=filters,
            fields=[
                "name",
                "first_name",
                "last_name",
                "employee_name",
                "cell_number",
                "personal_email",
                "company_email",
                "designation",
                "department",
                "branch",
                "image",
                "modified",
                "status"
            ]
        )

        tenant_bench_logger.info(f"Retrieved {len(employees)} active employees", "EMPLOYEE_SYNC")

        return create_success_response(
            message="Active employees retrieved successfully",
            data=employees
        )

    except Exception as e:
        return handle_api_exception(e, "EMPLOYEE_SYNC")


@frappe.whitelist(allow_guest=True)
def update_scheduled_trip_status(trip_id=None, status=None):
    """
    Update Scheduled Trip status without creating a Journey record.
    Used for lightweight "In Progress" updates.
    """
    try:
        # Validate sync request
        validate_sync_request()

        if not trip_id or not status:
            raise ValidationException("trip_id and status are required")

        if not frappe.db.exists("Scheduled Trip", trip_id):
            raise ResourceNotFoundException(f"Scheduled Trip {trip_id}")

        scheduled_trip = frappe.get_doc("Scheduled Trip", trip_id)
        scheduled_trip.status = status
        scheduled_trip.save(ignore_permissions=True)
        
        tenant_bench_logger.info(f"Scheduled Trip {trip_id} status updated to {status} via lightweight API", "JOURNEY_SYNC")

        return create_success_response(
            message=f"Scheduled Trip status updated to {status}",
            data={
                "trip_id": trip_id,
                "status": status
            }
        )

    except Exception as e:
        return handle_api_exception(e, "JOURNEY_SYNC")

@frappe.whitelist(allow_guest=True)
def extend_trip(trip_id=None, reason=None, new_destination=None):
    """
    Extend an active trip with a new destination and reason.
    Logs the extension to the trip's timeline and metadata.
    """
    try:
        # Validate sync request
        validate_sync_request()

        if not trip_id or not reason:
            raise ValidationException("trip_id and reason are required")

        # Determine DocType of the trip_id
        doctype = None
        if frappe.db.exists("Scheduled Trip", trip_id):
            doctype = "Scheduled Trip"
        elif frappe.db.exists("NetraNext Journey", trip_id):
            doctype = "NetraNext Journey"
        else:
            # Maybe it's a flutter_journey_id
            journey = frappe.db.get_value("NetraNext Journey", {"flutter_journey_id": trip_id}, "name")
            if journey:
                doctype = "NetraNext Journey"
                trip_id = journey
            else:
                raise ResourceNotFoundException(f"Trip {trip_id} not found")

        doc = frappe.get_doc(doctype, trip_id)

        # 1. Update Destination if provided (only for Journey, as Scheduled Trip is a Link field)
        if new_destination:
            if doctype == "NetraNext Journey" and hasattr(doc, "end_location"):
                doc.end_location = new_destination
                doc.save(ignore_permissions=True)

        # 2. Add Comment (Timeline Stop)
        dest_str = f" to {new_destination}" if new_destination else ""
        content = f"<b>Trip Extended</b>{dest_str}<br><b>Reason:</b> {reason}"
        
        comment = frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Comment",
            "reference_doctype": doctype,
            "reference_name": trip_id,
            "content": content
        })
        comment.insert(ignore_permissions=True)
        
        # 3. Update Metadata if Journey
        if doctype == "NetraNext Journey" and hasattr(doc, "metadata"):
            import json
            try:
                meta = json.loads(doc.metadata) if doc.metadata else {}
                stops = meta.get("extended_stops", [])
                stops.append({
                    "reason": reason,
                    "destination": new_destination,
                    "timestamp": frappe.utils.now()
                })
                meta["extended_stops"] = stops
                doc.metadata = json.dumps(meta)
                doc.save(ignore_permissions=True)
            except Exception as e:
                tenant_bench_logger.warning(f"Failed to update metadata for {trip_id}: {str(e)}", "JOURNEY_SYNC")

        tenant_bench_logger.info(f"Trip {trip_id} extended successfully. Reason: {reason}", "JOURNEY_SYNC")

        return create_success_response(
            message="Trip extended successfully",
            data={
                "trip_id": trip_id,
                "reason": reason,
                "new_destination": new_destination
            }
        )

    except Exception as e:
        return handle_api_exception(e, "JOURNEY_SYNC")

@frappe.whitelist(allow_guest=True)
def get_shift_reminders():
    """
    Get shift reminders (check-in/check-out) for active employees
    whose shifts are starting or ending within the 15-minute window.
    Called by central server to dispatch push notifications.
    """
    debug_logs = []
    try:
        # Validate sync request
        validate_sync_request()

        import pytz
        from datetime import timedelta
        from frappe.utils import get_system_timezone
        from hrms.hr.doctype.shift_assignment.shift_assignment import get_employee_shift

        now = frappe.utils.now_datetime()
        employees = frappe.get_all("Employee", filters={"status": "Active"}, fields=["name", "employee_name", "user_id"])
        
        system_tz = pytz.timezone(get_system_timezone() or "UTC")
        
        def to_utc(dt):
            if not dt:
                return None
            if dt.tzinfo is not None:
                return dt.astimezone(pytz.utc)
            return system_tz.localize(dt).astimezone(pytz.utc)

        def to_naive_local(dt):
            if not dt:
                return None
            if dt.tzinfo is not None:
                return dt.astimezone(system_tz).replace(tzinfo=None)
            return dt

        now_naive = to_naive_local(now)
        reminders = []
        
        debug_logs.append(f"Current local time (naive): {now_naive.strftime('%Y-%m-%d %H:%M:%S')}")
        debug_logs.append(f"Active employees count: {len(employees)}")
        
        for emp in employees:
            if not emp.user_id:
                debug_logs.append(f"Employee {emp.employee_name} ({emp.name}) skipped: No User ID linked.")
                continue
                
            shift_details = get_employee_shift(emp.name, now, consider_default_shift=True)
            if not shift_details or not shift_details.get("start_datetime"):
                debug_logs.append(f"Employee {emp.employee_name} ({emp.name}) skipped: No shift found for today.")
                continue
                
            start_dt = to_naive_local(shift_details.get("start_datetime"))
            end_dt = to_naive_local(shift_details.get("end_datetime"))
            
            debug_logs.append(
                f"Employee {emp.employee_name} ({emp.name}) has shift '{shift_details.get('shift_type')}' today: "
                f"Start={start_dt.strftime('%H:%M:%S')}, End={end_dt.strftime('%H:%M:%S')}"
            )
            
            # Check-in reminder window (run window: within 15 minutes of shift start)
            time_since_start = (now_naive - start_dt).total_seconds() / 60
            debug_logs.append(f"  Check-in: time_since_start = {time_since_start:.2f} minutes.")
            if 0 <= time_since_start <= 15:
                # Check if check-in log exists for today within the start threshold (convert to UTC for database query)
                checkin_threshold_utc = to_utc(start_dt - timedelta(hours=2))
                checkin_exists = frappe.db.exists("Employee Checkin", {
                    "employee": emp.name,
                    "log_type": "IN",
                    "time": [">=", checkin_threshold_utc]
                })
                if not checkin_exists:
                    reminders.append({
                        "user_id": emp.user_id,
                        "employee_name": emp.employee_name,
                        "type": "check_in",
                        "shift_time": start_dt.strftime('%I:%M %p')
                    })
                    debug_logs.append("  Check-in: Added to reminder list.")
                else:
                    debug_logs.append("  Check-in: Skipped because check-in log already exists.")
            else:
                debug_logs.append(f"  Check-in: Skipped because time_since_start ({time_since_start:.2f} mins) is outside 0..15 window.")
                    
            # Check-out reminder window (run window: within 15 minutes of shift end)
            time_since_end = (now_naive - end_dt).total_seconds() / 60
            debug_logs.append(f"  Check-out: time_since_end = {time_since_end:.2f} minutes.")
            if 0 <= time_since_end <= 15:
                # Check if check-out log exists for today within the end threshold (convert to UTC for database query)
                checkout_threshold_utc = to_utc(end_dt - timedelta(hours=2))
                checkout_exists = frappe.db.exists("Employee Checkin", {
                    "employee": emp.name,
                    "log_type": "OUT",
                    "time": [">=", checkout_threshold_utc]
                })
                if not checkout_exists:
                    reminders.append({
                        "user_id": emp.user_id,
                        "employee_name": emp.employee_name,
                        "type": "check_out",
                        "shift_time": end_dt.strftime('%I:%M %p')
                    })
                    debug_logs.append("  Check-out: Added to reminder list.")
                else:
                    debug_logs.append("  Check-out: Skipped because check-out log already exists.")
            else:
                debug_logs.append(f"  Check-out: Skipped because time_since_end ({time_since_end:.2f} mins) is outside 0..15 window.")
                    
        # Log all debug statements
        frappe.log_error(title="Shift Reminders Client Debug", message="\n".join(debug_logs))
        return create_success_response("Shift reminders retrieved successfully", reminders)

    except Exception as e:
        frappe.log_error(title="Shift Reminders Client Exception", message=f"{str(e)}\nLogs:\n" + "\n".join(debug_logs))
        return handle_api_exception(e, "EMPLOYEE_SYNC")

