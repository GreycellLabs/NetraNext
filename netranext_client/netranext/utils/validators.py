"""
Validation utilities for NetraNext API endpoints
"""
import re
from typing import List, Dict, Any
import frappe


def validate_required_fields(
    data: Dict[str, Any],
    required_fields: List[str]
) -> None:
    """
    Validate that all required fields are present in data

    Args:
        data: Data dictionary to validate
        required_fields: List of required field names

    Raises:
        ValueError: If any required field is missing or empty
    """
    missing_fields = []

    for field in required_fields:
        if field not in data or not data[field]:
            missing_fields.append(field)

    if missing_fields:
        raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")


def validate_email(email: str) -> bool:
    """
    Validate email format

    Args:
        email: Email address to validate

    Returns:
        bool: True if valid email format

    Raises:
        ValueError: If email format is invalid
    """
    if not email:
        raise ValueError("Email is required")

    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        raise ValueError("Invalid email format")

    return True


def validate_employee_exists(employee_id: str) -> bool:
    """
    Validate that an employee exists in the system

    Args:
        employee_id: Employee ID to validate

    Returns:
        bool: True if employee exists

    Raises:
        ValueError: If employee doesn't exist
    """
    if not frappe.db.exists("Employee", employee_id):
        raise ValueError(f"Employee {employee_id} not found")

    return True


def validate_gps_coordinates(latitude: float, longitude: float) -> bool:
    """
    Validate GPS coordinates

    Args:
        latitude: Latitude value
        longitude: Longitude value

    Returns:
        bool: True if coordinates are valid

    Raises:
        ValueError: If coordinates are invalid
    """
    if not (-90 <= latitude <= 90):
        raise ValueError(f"Invalid latitude: {latitude}. Must be between -90 and 90")

    if not (-180 <= longitude <= 180):
        raise ValueError(f"Invalid longitude: {longitude}. Must be between -180 and 180")

    return True


def validate_date_format(date_string: str, date_format: str = "%Y-%m-%d") -> bool:
    """
    Validate date string format

    Args:
        date_string: Date string to validate
        date_format: Expected date format (default: YYYY-MM-DD)

    Returns:
        bool: True if date format is valid

    Raises:
        ValueError: If date format is invalid
    """
    from datetime import datetime

    try:
        datetime.strptime(date_string, date_format)
        return True
    except ValueError:
        raise ValueError(f"Invalid date format: {date_string}. Expected format: {date_format}")


def validate_api_key_format(api_key: str) -> bool:
    """
    Validate API key format

    Args:
        api_key: API key to validate

    Returns:
        bool: True if API key format is valid

    Raises:
        ValueError: If API key format is invalid
    """
    if not api_key or len(api_key) < 16:
        raise ValueError("Invalid API key format. Must be at least 16 characters")

    return True
