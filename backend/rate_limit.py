"""
rate_limit.py — Simple in-memory rate limiting middleware

Prevents abuse without external dependencies.
Tracks requests per IP with configurable limits.
"""

import time
from collections import defaultdict
from typing import Dict, Tuple
from fastapi import Request
from functools import wraps


class RateLimiter:
    """In-memory rate limiter using token bucket algorithm"""
    
    def __init__(self, requests_per_minute: int = 60, requests_per_hour: int = 1000):
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        
        # Track requests: {ip: [(timestamp, endpoint)]}
        self.requests: Dict[str, list] = defaultdict(list)
    
    def get_client_ip(self, request: Request) -> str:
        """Extract client IP from request"""
        # Check X-Forwarded-For header first (for proxies)
        if "x-forwarded-for" in request.headers:
            return request.headers["x-forwarded-for"].split(",")[0].strip()
        return request.client.host if request.client else "unknown"
    
    def is_allowed(self, request: Request) -> Tuple[bool, int, int]:
        """
        Check if request is allowed
        
        Returns:
            (is_allowed, retry_after_seconds, remaining_requests)
        """
        client_ip = self.get_client_ip(request)
        now = time.time()
        minute_ago = now - 60
        hour_ago = now - 3600
        
        # Clean old requests
        self.requests[client_ip] = [
            (ts, ep) for ts, ep in self.requests[client_ip]
            if ts > hour_ago
        ]
        
        # Count recent requests
        requests_this_minute = len([ts for ts, _ in self.requests[client_ip] if ts > minute_ago])
        requests_this_hour = len(self.requests[client_ip])
        
        # Check limits
        if requests_this_minute >= self.requests_per_minute:
            retry_after = int(minute_ago + 60 - now) + 1
            return False, retry_after, 0
        
        if requests_this_hour >= self.requests_per_hour:
            retry_after = int(hour_ago + 3600 - now) + 1
            return False, retry_after, 0
        
        # Record this request
        endpoint = f"{request.method} {request.url.path}"
        self.requests[client_ip].append((now, endpoint))
        
        remaining = self.requests_per_minute - requests_this_minute - 1
        return True, 0, remaining


# Global rate limiter instance
_rate_limiter = None


def get_rate_limiter() -> RateLimiter:
    """Get or create rate limiter"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(
            requests_per_minute=60,
            requests_per_hour=1000,
        )
    return _rate_limiter
