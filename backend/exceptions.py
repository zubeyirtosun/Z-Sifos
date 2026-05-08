"""
exceptions.py — Custom application exceptions with proper error codes

Provides structured exception classes for different failure scenarios.
Used for consistent error responses across API.
"""

from fastapi import HTTPException, status
from typing import Optional, Any, Dict


class ValidationError(HTTPException):
    """Invalid input data"""
    def __init__(self, detail: str, field: Optional[str] = None):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "validation_error", "message": detail, "field": field}
        )


class NotFoundError(HTTPException):
    """Resource not found"""
    def __init__(self, resource: str, resource_id: Any):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"{resource} with ID {resource_id} not found"}
        )


class ConflictError(HTTPException):
    """Resource already exists or conflict"""
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "conflict", "message": detail}
        )


class UnauthorizedError(HTTPException):
    """Authentication required"""
    def __init__(self, detail: str = "Authentication required"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized", "message": detail}
        )


class ForbiddenError(HTTPException):
    """Access denied"""
    def __init__(self, detail: str = "Access denied"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "message": detail}
        )


class RateLimitError(HTTPException):
    """Too many requests"""
    def __init__(self, retry_after: int = 60):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limit", "message": "Too many requests", "retry_after": retry_after},
            headers={"Retry-After": str(retry_after)}
        )


class ServiceError(HTTPException):
    """Internal server error (service-specific)"""
    def __init__(self, service: str, detail: str):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "service_error", "service": service, "message": detail}
        )


class InternalError(HTTPException):
    """Generic internal server error"""
    def __init__(self, detail: str = "Internal server error"):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "internal_error", "message": detail}
        )
