"""
Response formatter utilities for NetraNext API endpoints
Provides standardized response formatting for tenant bench APIs
"""
from datetime import datetime
from typing import Any, Dict, Optional


def create_success_response(
    message: str,
    data: Optional[Dict[str, Any]] = None,
    status_code: int = 200
) -> Dict[str, Any]:
    """
    Create a standardized success response

    Args:
        message: Success message
        data: Optional data payload
        status_code: HTTP status code (default: 200)

    Returns:
        dict: Formatted success response
    """
    response = {
        "status": "success",
        "message": message,
        "timestamp": datetime.now().isoformat(),
        "status_code": status_code
    }

    if data is not None:
        response["data"] = data

    return response


def create_error_response(
    message: str,
    error_code: Optional[str] = None,
    status_code: int = 400,
    details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a standardized error response

    Args:
        message: Error message
        error_code: Optional error code
        status_code: HTTP status code (default: 400)
        details: Optional error details

    Returns:
        dict: Formatted error response
    """
    response = {
        "status": "error",
        "message": message,
        "timestamp": datetime.now().isoformat(),
        "status_code": status_code
    }

    if error_code:
        response["error_code"] = error_code

    if details:
        response["details"] = details

    return response


def format_sync_response(
    success: bool,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    error_details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Format a sync API response for tenant bench communication

    Args:
        success: Whether the operation succeeded
        message: Human-readable message
        data: Optional data payload for success responses
        error_details: Optional error details for error responses

    Returns:
        dict: Formatted sync response
    """
    if success:
        return create_success_response(message, data)
    else:
        return create_error_response(message, details=error_details)
