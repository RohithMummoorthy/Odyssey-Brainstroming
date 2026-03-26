"""Request middleware registered as before_request on the Flask app.

Responsibilities:
  1. Skip enforcement for whitelisted paths (/login, /health, /static).
  2. Read the allowed_ip from app_config (cached in-process for 60 seconds
     to avoid a DB round-trip on every request).
  3. If allowed_ip is a non-empty string and the client IP does not match,
     return a 403 JSON error telling participants to use the venue Wi-Fi.

Registration (app/__init__.py):
    from app.middleware import init_middleware
    init_middleware(app)
"""
import logging
import time
from typing import Optional

from flask import Flask, request, jsonify

from app.models.db import get_supabase

log = logging.getLogger(__name__)

# ── In-process cache for allowed_ip ────────────────────────────────────────
_CACHE_TTL_SECONDS: int = 60

_cached_ip: Optional[str] = None
_cache_loaded_at: float = 0.0          # Unix timestamp of last DB read

# Paths that are always allowed through regardless of IP
_SKIP_PREFIXES = ("/login", "/static", "/health", "/logout", "/favicon", "/admin", "/leaderboard")


def _get_allowed_ip() -> str:
    """Return allowed_ip from app_config, using a 60-second in-memory cache.

    Returns:
        The allowed IP string, or '' if not configured (meaning open access).
    """
    global _cached_ip, _cache_loaded_at

    now = time.monotonic()
    if _cached_ip is not None and (now - _cache_loaded_at) < _CACHE_TTL_SECONDS:
        return _cached_ip

    # Cache miss — fetch from Supabase
    try:
        result = (
            get_supabase()
            .table("app_config")
            .select("value")
            .eq("key", "allowed_ip")
            .single()
            .execute()
        )
        value: str = result.data.get("value", "") if result.data else ""
    except Exception as exc:
        log.warning("middleware: could not fetch allowed_ip from app_config: %s", exc)
        # Fail open — don't block participants because of a DB glitch
        value = ""

    _cached_ip = value
    _cache_loaded_at = now
    return value


def clear_ip_cache() -> None:
    """Invalidate the in-memory allowed_ip cache.

    Call this immediately after writing a new value to app_config so
    the next request re-reads from the DB without waiting 60 seconds.
    """
    global _cached_ip, _cache_loaded_at
    _cached_ip = None
    _cache_loaded_at = 0.0


def get_client_ip() -> str:
    """Public wrapper — return the real client IP from the current request."""
    return _get_client_ip()


def _get_client_ip() -> str:
    """Return the real client IP, honouring X-Forwarded-For (Render / proxies)."""
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        # May be a comma-separated list; the first entry is the originating client
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or ""


def _is_skipped_path(path: str) -> bool:
    """Return True if the request path should bypass IP enforcement."""
    for prefix in _SKIP_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def init_middleware(app: Flask) -> None:
    """Register all before_request hooks on the given Flask app."""

    @app.before_request
    def enforce_allowed_ip():
        """IP allow-list gate — runs before every non-whitelisted request."""
        if _is_skipped_path(request.path):
            return None   # Continue normally

        allowed_ip = _get_allowed_ip()

        if not allowed_ip:
            # Empty string means the admin hasn't locked the event to a
            # specific IP yet — allow all traffic.
            return None

        client_ip = _get_client_ip()
        if client_ip != allowed_ip:
            log.warning(
                "IP violation: client=%s allowed=%s path=%s",
                client_ip,
                allowed_ip,
                request.path,
            )
            return (
                jsonify(
                    {
                        "error":   "network_violation",
                        "message": "Use venue Wi-Fi",
                    }
                ),
                403,
            )

        return None   # IP matches — continue normally
