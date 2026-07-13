"""
Logging utilities for NetraNext API endpoints
Provides structured logging for tenant bench operations
"""
import frappe
from datetime import datetime
from typing import Optional


class TenantBenchLogger:
    """
    Structured logger for tenant bench operations
    Provides consistent logging format for debugging and monitoring
    """

    @staticmethod
    def _log(message: str, level: str, module: Optional[str] = None, exc_info: bool = False):
        """
        Internal logging method that writes to Frappe's log system

        Args:
            message: Log message
            level: Log level (INFO, WARNING, ERROR, DEBUG)
            module: Module name for categorization
            exc_info: Include exception info if True
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        module_prefix = f"[{module}] " if module else ""
        formatted_message = f"{module_prefix}{message} at {timestamp}"

        if level == "INFO":
            frappe.logger().info(formatted_message)
        elif level == "WARNING":
            frappe.logger().warning(formatted_message)
        elif level == "ERROR":
            frappe.log_error(title="TenantBench-ERROR", message=formatted_message)
        elif level == "DEBUG":
            frappe.logger().debug(formatted_message)

    @staticmethod
    def info(message: str, module: Optional[str] = None):
        """Log info message"""
        TenantBenchLogger._log(message, "INFO", module)

    @staticmethod
    def warning(message: str, module: Optional[str] = None):
        """Log warning message"""
        TenantBenchLogger._log(message, "WARNING", module)

    @staticmethod
    def error(message: str, module: Optional[str] = None, exc_info: bool = False):
        """Log error message"""
        TenantBenchLogger._log(message, "ERROR", module, exc_info)

    @staticmethod
    def debug(message: str, module: Optional[str] = None):
        """Log debug message (only in developer mode)"""
        TenantBenchLogger._log(message, "DEBUG", module)

    @staticmethod
    def separator():
        """Log a separator line for better log readability"""
        TenantBenchLogger.info("=" * 50, "TENANT_BENCH")


# Global logger instance
tenant_bench_logger = TenantBenchLogger()
