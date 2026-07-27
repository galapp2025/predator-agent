"""
API Authentication & Rate Limiting Middleware for BlackOpps FastAPI.

Drop-in security layer:
  - X-API-Key header validation
  - Rate limiting per API key (100 req/min)
  - IP-based fallback rate limiting (30 req/min)
  - Security headers injection

Usage in FastAPI app:
    from .intelligence.auth import AuthMiddleware, RateLimiter

    auth = AuthMiddleware(api_keys={"sk-xxx": "campaign-1"})
    limiter = RateLimiter()

    @app.middleware("http")
    async def security_middleware(request, call_next):
        # Rate limit
        await limiter.check(request)
        # Authenticate
        api_key = request.headers.get("X-API-Key")
        if not auth.validate(api_key):
            return JSONResponse(status_code=401, content={"error": "Invalid API key"})
        response = await call_next(request)
        auth.inject_security_headers(response)
        return response
"""

import hashlib
import hmac
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---- API Key Validation ----

class AuthMiddleware:
    """
    Validates X-API-Key header against known keys.
    Uses constant-time comparison to prevent timing attacks.

    In production, replace with DB lookup or external auth service.
    """

    def __init__(self, api_keys: dict[str, str] | None = None):
        """
        Args:
            api_keys: Mapping of API key → campaign/client identifier.
                      If None, loads from BLACKOPPS_API_KEYS env var (comma-separated).
        """
        self._keys: dict[str, str] = {}
        if api_keys:
            self._keys = {self._normalize(k): v for k, v in api_keys.items()}
        else:
            self._load_from_env()

    def _load_from_env(self):
        import os
        keys_str = os.getenv("BLACKOPPS_API_KEYS", "")
        if keys_str:
            for pair in keys_str.split(","):
                pair = pair.strip()
                if ":" in pair:
                    key, name = pair.split(":", 1)
                    self._keys[self._normalize(key.strip())] = name.strip()

    @staticmethod
    def _normalize(key: str) -> str:
        return key.strip()

    def validate(self, api_key: str | None) -> bool:
        """Constant-time API key validation."""
        if not api_key:
            return False
        normalized = self._normalize(api_key)
        for stored_key in self._keys:
            if hmac.compare_digest(normalized.encode(), stored_key.encode()):
                return True
        return False

    def get_client(self, api_key: str) -> Optional[str]:
        """Get client name for a valid API key."""
        normalized = self._normalize(api_key)
        return self._keys.get(normalized)

    def inject_security_headers(self, response):
        """Add security headers to responses."""
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response

    @property
    def is_configured(self) -> bool:
        return len(self._keys) > 0

    def key_count(self) -> int:
        return len(self._keys)


# ---- Rate Limiter (In-Memory) ----

class RateLimiter:
    """
    Token-bucket rate limiter.

    For production, replace with Redis-backed implementation:
      - redis-py + Lua script for atomic bucket operations
      - Per-campaign tiered limits (basic/pro/enterprise)
    """

    def __init__(self, requests_per_minute: int = 100,
                 ip_requests_per_minute: int = 30,
                 burst_multiplier: float = 1.5):
        self.rpm = requests_per_minute
        self.ip_rpm = ip_requests_per_minute
        self.burst = int(requests_per_minute * burst_multiplier)
        self.ip_burst = int(ip_requests_per_minute * burst_multiplier)

        # Token buckets: {key: (tokens, last_refill_timestamp)}
        self._buckets: dict[str, tuple[float, float]] = {}
        self._ip_buckets: dict[str, tuple[float, float]] = {}

        # Cleanup every 5 minutes
        self._last_cleanup = time.time()
        self._cleanup_interval = 300

    async def check(self, request) -> bool:
        """
        Check rate limit for this request.
        Returns True if allowed, False if rate limited.

        Raises no exception — always returns bool for middleware use.
        """
        now = time.time()
        self._maybe_cleanup(now)

        client_ip = self._get_client_ip(request)
        api_key = request.headers.get("X-API-Key", "")

        # API key-based limit
        if api_key:
            key_bucket = f"key:{self._hash_key(api_key)}"
            if not self._consume_token(key_bucket, self.rpm, self.burst, now):
                logger.warning(f"Rate limit hit for API key: {self._hash_key(api_key)[:8]}...")
                return False

        # IP-based limit (always enforced as fallback)
        ip_bucket = f"ip:{client_ip}"
        if not self._consume_token(ip_bucket, self.ip_rpm, self.ip_burst, now):
            logger.warning(f"Rate limit hit for IP: {client_ip}")
            return False

        return True

    def _consume_token(self, bucket_key: str, refill_rate: float,
                        max_tokens: float, now: float) -> bool:
        """Token bucket algorithm. Returns True if token consumed."""
        store = self._ip_buckets if bucket_key.startswith("ip:") else self._buckets

        if bucket_key not in store:
            store[bucket_key] = (max_tokens - 1, now)
            return True

        tokens, last_refill = store[bucket_key]
        elapsed = now - last_refill

        # Refill tokens
        tokens = min(max_tokens, tokens + elapsed * (refill_rate / 60.0))

        if tokens >= 1:
            store[bucket_key] = (tokens - 1, now)
            return True

        store[bucket_key] = (tokens, now)
        return False

    def _maybe_cleanup(self, now: float):
        if now - self._last_cleanup < self._cleanup_interval:
            return
        cutoff = now - 600  # Remove buckets older than 10 minutes
        for store in (self._buckets, self._ip_buckets):
            stale = [k for k, (_, ts) in store.items() if ts < cutoff]
            for k in stale:
                del store[k]
        self._last_cleanup = now

    @staticmethod
    def _get_client_ip(request) -> str:
        """Extract client IP from request headers."""
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP", "")
        if real_ip:
            return real_ip
        if hasattr(request, "client") and request.client:
            return request.client.host
        return "unknown"

    @staticmethod
    def _hash_key(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def stats(self) -> dict:
        """Return current rate limiter statistics."""
        return {
            "active_api_key_buckets": len(self._buckets),
            "active_ip_buckets": len(self._ip_buckets),
            "rpm_limit": self.rpm,
            "ip_rpm_limit": self.ip_rpm,
        }


# ---- Security Headers Middleware (standalone, no auth) ----

class SecurityHeadersMiddleware:
    """Adds security headers without requiring authentication.
    For public-facing endpoints that still need security hardening."""

    async def __call__(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
