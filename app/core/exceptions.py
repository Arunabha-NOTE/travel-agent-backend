from __future__ import annotations

from typing import Any


class AppException(Exception):
    """
    Base exception class for the application.

    All custom exceptions should inherit from this class.
    """

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        """
        Initialize an AppException.

        Args:
            message: Human-readable error message
            status_code: HTTP status code (default: 500)
            error_code: Machine-readable error code (e.g., "INVALID_INPUT")
            details: Additional error details as a dict
        """
        self.message = message
        self.status_code = status_code
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for JSON response."""
        return {
            "error": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class ValidationError(AppException):
    """
    Raised when input validation fails.

    HTTP Status: 422 Unprocessable Entity
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            status_code=422,
            error_code="VALIDATION_ERROR",
            details=details,
        )


class ResourceNotFoundError(AppException):
    """
    Raised when a requested resource is not found.

    HTTP Status: 404 Not Found
    """

    def __init__(self, resource: str, resource_id: str | int | None = None):
        message = f"{resource} not found"
        if resource_id:
            message += f" (ID: {resource_id})"

        super().__init__(
            message=message,
            status_code=404,
            error_code="RESOURCE_NOT_FOUND",
            details={"resource": resource, "resource_id": resource_id},
        )


class UnauthorizedError(AppException):
    """
    Raised when authentication fails or credentials are missing.

    HTTP Status: 401 Unauthorized
    """

    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            message=message,
            status_code=401,
            error_code="UNAUTHORIZED",
        )


class ForbiddenError(AppException):
    """
    Raised when user lacks permission for an action.

    HTTP Status: 403 Forbidden
    """

    def __init__(self, message: str = "Permission denied"):
        super().__init__(
            message=message,
            status_code=403,
            error_code="FORBIDDEN",
        )


class ConflictError(AppException):
    """
    Raised when a resource already exists or conflicts with existing data.

    HTTP Status: 409 Conflict
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            status_code=409,
            error_code="CONFLICT",
            details=details,
        )


class DatabaseError(AppException):
    """
    Raised when a database operation fails.

    HTTP Status: 500 Internal Server Error
    """

    def __init__(self, message: str = "Database operation failed"):
        super().__init__(
            message=message,
            status_code=500,
            error_code="DATABASE_ERROR",
        )


class ServiceUnavailableError(AppException):
    """
    Raised when an external service or resource is unavailable.

    HTTP Status: 503 Service Unavailable
    """

    def __init__(self, service: str, message: str | None = None):
        msg = message or f"{service} is currently unavailable"
        super().__init__(
            message=msg,
            status_code=503,
            error_code="SERVICE_UNAVAILABLE",
            details={"service": service},
        )
