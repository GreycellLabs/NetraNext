"""
Error handling utilities for NetraNext API endpoints
Provides centralized error handling and reporting
"""
import frappe
from typing import Dict, Any
from netranext_client.netranext.utils.logger import tenant_bench_logger
from netranext_client.netranext.utils.response_formatter import create_error_response


class TenantBenchException(Exception):
    """Base exception for tenant bench operations"""

    def __init__(self, message: str, error_code: str = None):
        self.message = message
        self.error_code = error_code or "TENANT_BENCH_ERROR"
        super().__init__(self.message)


class AuthenticationException(TenantBenchException):
    """Exception for authentication failures"""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, "AUTHENTICATION_ERROR")


class ValidationException(TenantBenchException):
    """Exception for validation failures"""

    def __init__(self, message: str = "Validation failed"):
        super().__init__(message, "VALIDATION_ERROR")


class ResourceNotFoundException(TenantBenchException):
    """Exception for resource not found"""

    def __init__(self, resource_type: str = "Resource"):
        super().__init__(f"{resource_type} not found", "RESOURCE_NOT_FOUND")


class DataAccessException(TenantBenchException):
    """Exception for data access failures"""

    def __init__(self, message: str = "Data access failed"):
        super().__init__(message, "DATA_ACCESS_ERROR")


class SyncException(TenantBenchException):
    """Exception for sync operation failures"""

    def __init__(self, message: str = "Sync operation failed"):
        super().__init__(message, "SYNC_ERROR")


def handle_api_exception(exception: Exception, module: str = "TENANT_BENCH_API") -> Dict[str, Any]:
    """
    Handle API exceptions and return formatted error response

    Args:
        exception: The exception to handle
        module: Module name for logging

    Returns:
        dict: Formatted error response
    """
    # Log the exception
    if isinstance(exception, TenantBenchException):
        tenant_bench_logger.error(
            f"{exception.error_code}: {exception.message}",
            module,
            exc_info=True
        )

        return create_error_response(
            message=exception.message,
            error_code=exception.error_code,
            status_code=400
        )
    else:
        # Log unexpected exceptions
        tenant_bench_logger.error(
            f"Unexpected error: {str(exception)}",
            module,
            exc_info=True
        )

        return create_error_response(
            message="An unexpected error occurred. Please try again.",
            error_code="INTERNAL_ERROR",
            status_code=500
        )


def log_and_return_error(message: str, module: str = "TENANT_BENCH_API", status_code: int = 400) -> Dict[str, Any]:
    """
    Log error message and return formatted error response

    Args:
        message: Error message
        module: Module name for logging
        status_code: HTTP status code

    Returns:
        dict: Formatted error response
    """
    tenant_bench_logger.error(message, module)
    return create_error_response(message, status_code=status_code)
