"""
validators.py — Input validation helpers

Provides reusable validation functions for common data types.
Prevents invalid data from entering the system early.
"""

import re
from typing import Optional
from backend.exceptions import ValidationError


def validate_string(value: str, min_length: int = 1, max_length: int = 10000, field_name: str = "field") -> str:
    """
    Validate string input
    
    Args:
        value: String to validate
        min_length: Minimum allowed length
        max_length: Maximum allowed length
        field_name: Field name for error messages
    
    Returns:
        Validated string (stripped)
    
    Raises:
        ValidationError: If validation fails
    """
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string", field=field_name)
    
    value = value.strip()
    
    if len(value) < min_length:
        raise ValidationError(f"{field_name} must be at least {min_length} characters", field=field_name)
    
    if len(value) > max_length:
        raise ValidationError(f"{field_name} must not exceed {max_length} characters", field=field_name)
    
    return value


def validate_identifier(value: str, field_name: str = "identifier") -> str:
    """Validate identifier (alphanumeric, underscore, hyphen)"""
    value = validate_string(value, min_length=1, max_length=100, field_name=field_name)
    
    if not re.match(r"^[a-zA-Z0-9_-]+$", value):
        raise ValidationError(f"{field_name} must contain only alphanumeric characters, underscores, and hyphens", field=field_name)
    
    return value


def validate_email(email: str) -> str:
    """Validate email format"""
    email = email.strip().lower()
    
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        raise ValidationError("Invalid email format", field="email")
    
    return email


def validate_positive_int(value: int, field_name: str = "value", min_val: int = 1, max_val: Optional[int] = None) -> int:
    """Validate positive integer"""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{field_name} must be an integer", field=field_name)
    
    if value < min_val:
        raise ValidationError(f"{field_name} must be at least {min_val}", field=field_name)
    
    if max_val is not None and value > max_val:
        raise ValidationError(f"{field_name} must not exceed {max_val}", field=field_name)
    
    return value


def validate_choice(value: str, choices: list, field_name: str = "choice") -> str:
    """Validate that value is in allowed choices"""
    if value not in choices:
        raise ValidationError(f"{field_name} must be one of: {', '.join(choices)}", field=field_name)
    return value


def validate_model_name(model_name: str) -> str:
    """Validate model name format (provider:name)"""
    if not model_name or ":" not in model_name:
        raise ValidationError("Model name must be in format 'provider:model'", field="model_name")
    
    parts = model_name.split(":")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValidationError("Model name must be in format 'provider:model'", field="model_name")
    
    return model_name


def validate_temperature(value: float) -> float:
    """Validate temperature parameter"""
    if not isinstance(value, (int, float)):
        raise ValidationError("Temperature must be a number", field="temperature")
    
    if value < 0.0 or value > 2.0:
        raise ValidationError("Temperature must be between 0.0 and 2.0", field="temperature")
    
    return float(value)


def validate_top_p(value: float) -> float:
    """Validate top_p parameter"""
    if not isinstance(value, (int, float)):
        raise ValidationError("Top P must be a number", field="top_p")
    
    if value < 0.0 or value > 1.0:
        raise ValidationError("Top P must be between 0.0 and 1.0", field="top_p")
    
    return float(value)
