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
        checkin_doc = frappe.get_doc({
            "doctype": "Employee Checkin",
            "employee": att_data["employee_id"],
            "time": att_data["time"],
            "log_type": att_data["log_type"],
            "device_id": att_data.get("device_id", "NetraNext"),
            "latitude": att_data.get("latitude"),
            "longitude": att_data.get("longitude"),
            "location_address": att_data.get("location_address"),
            "photo_proof": local_photo_url,
            "skip_auto_attendance": att_data.get("skip_auto_attendance", 0)
        })

        checkin_doc.insert(ignore_permissions=True)

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
    Creates or updates NetraNext Face Registration on tenant bench

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
        validate_required_fields(face_data, ["employee_id", "face_id", "embedding"])

        # Check if employee exists
        validate_employee_exists(face_data["employee_id"])

        # Check if NetraNext Face Registration DocType exists
        if not frappe.db.exists("DocType", "NetraNext Face Registration"):
            raise ResourceNotFoundException("NetraNext Face Registration DocType")

        # Check if face registration already exists
        existing = frappe.db.exists(
            "NetraNext Face Registration",
            {"employee": face_data["employee_id"]}
        )

        if existing:
            # Update existing registration
            frappe.db.set_value(
                "NetraNext Face Registration",
                existing,
                {
                    "face_id": face_data["face_id"],
                    "face_embedding": json.dumps(face_data["embedding"]) if isinstance(face_data["embedding"], list) else face_data["embedding"],
                    "face_photo": face_data.get("face_photo_url"),
                    "registered_date": face_data.get("registered_date")
                }
            )
            face_name = existing
            action = "updated"
        else:
            # Create new registration
            face_doc = frappe.get_doc({
                "doctype": "NetraNext Face Registration",
                "employee": face_data["employee_id"],
                "face_id": face_data["face_id"],
                "face_embedding": json.dumps(face_data["embedding"]) if isinstance(face_data["embedding"], list) else face_data["embedding"],
                "face_photo": face_data.get("face_photo_url"),
                "registered_date": face_data.get("registered_date")
            })
            face_doc.insert(ignore_permissions=True)
            face_name = face_doc.name
            action = "created"

        # Update employee attendance_device_id
        frappe.db.set_value(
            "Employee",
            face_data["employee_id"],
            "attendance_device_id",
            face_data["face_id"]
        )

        tenant_bench_logger.info(f"Face registration {action} for employee {face_data['employee_id']}", "FACE_SYNC")

        return create_success_response(
            message=f"Face registration {action} successfully",
            data={
                "face_name": face_name,
                "face_id": face_data["face_id"],
                "employee_id": face_data["employee_id"],
                "action": action
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
        }

        for field, value in optional_mappings.items():
            if field in field_names and value is not None:
                doc_data[field] = value

        journey_doc = frappe.get_doc(doc_data)
        journey_doc.insert(ignore_permissions=True)

        tenant_bench_logger.info(f"Journey stored for employee {journey_data['employee_id']}: {journey_doc.name}", "JOURNEY_SYNC")

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

        # Build response data
        response_data = {
            "user": user,
            "full_name": user_doc.full_name,
            "email": user_doc.email,
            "user_type": user_doc.user_type,
            "enabled": user_doc.enabled,
            "employee_id": employee_id,
            "employee_data": employee_data
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
                "location_address", "marked_by", "creation", "modified"
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

        # Check if NetraNext Journey DocType exists
        if not frappe.db.exists("DocType", "NetraNext Journey"):
            return create_success_response(
                message="No journeys found",
                data={"journeys": [], "total": 0}
            )

        filters = []
        if employee_id:
            filters.append(["employee", "=", employee_id])
        if status:
            filters.append(["status", "=", status])

        # Find field names
        journey_meta = frappe.get_meta("NetraNext Journey")
        field_names = [f.fieldname for f in journey_meta.fields]
        
        # Build fields to query
        query_fields = [
            "name", "employee", "status", "start_time", "end_time", 
            "start_location", "end_location", "creation"
        ]
        
        # Add optional fields if they exist
        for f in ["journey_name", "distance_km", "flutter_journey_id", "user_id", 
                 "original_points_count", "simplified_points_count", 
                 "encoded_polyline", "metadata", "duration_seconds"]:
            if f in field_names:
                query_fields.append(f)

        trips = frappe.get_all(
            "NetraNext Journey",
            filters=filters,
            fields=query_fields,
            order_by="creation desc",
            limit=int(limit),
            ignore_permissions=True
        )
        
        import json

        # Filter by user_id if provided (search in metadata or user_id field)
        if user_id and trips:
            filtered_trips = []
            for trip in trips:
                if trip.get("user_id") == user_id:
                    filtered_trips.append(trip)
                    continue

                if trip.get("metadata"):
                    try:
                        metadata = json.loads(trip.metadata) if isinstance(trip.metadata, str) else trip.metadata
                        if metadata.get("user_id") == user_id or metadata.get("flutter_data", {}).get("userId") == user_id:
                            filtered_trips.append(trip)
                    except:
                        pass
            trips = filtered_trips

        # Convert to Flutter format
        journeys = []
        for trip in trips:
            metadata = {}
            if trip.get("metadata"):
                try:
                    metadata = json.loads(trip.metadata) if isinstance(trip.metadata, str) else trip.metadata
                except:
                    pass

            journey = {
                "id": trip.get("flutter_journey_id") or metadata.get("journey_id") or trip.name,
                "userId": trip.get("user_id") or metadata.get("user_id") or trip.employee,
                "startDate": str(trip.start_time) if trip.get("start_time") else None,
                "endDate": str(trip.end_time) if trip.get("end_time") else None,
                "isActive": trip.status == "In Progress",
                "startAddress": trip.get("start_location") or metadata.get("start_address", ""),
                "endAddress": trip.get("end_location") or metadata.get("end_address", ""),
                "distanceKm": trip.get("distance_km") or 0.0,
                "durationSeconds": trip.get("duration_seconds") or 0,
                "pointsCount": trip.get("original_points_count") or 0,
                "simplifiedPoints": trip.get("simplified_points_count") or 0,
                "encodedPolyline": trip.get("encoded_polyline") or "",
                "tripId": trip.name,
                "status": trip.status,
                "createdAt": str(trip.creation)
            }
            journeys.append(journey)

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
