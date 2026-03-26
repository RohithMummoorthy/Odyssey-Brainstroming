"""Authentication service.

Provides:
  - JWT creation / verification
  - bcrypt PIN hashing / verification
  - @require_auth decorator for protecting Flask routes
"""
import os
import functools
from datetime import datetime, timezone, timedelta
from typing import Any

import bcrypt
import jwt
from flask import request, g, jsonify


# ── Default token lifetime (overridden per-event by /login logic) ──────────
_DEFAULT_DURATION_SECONDS = 3 * 60 * 60   # 3 hours


def _secret() -> str:
    """Return the JWT signing secret from the environment."""
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise EnvironmentError("JWT_SECRET environment variable is not set.")
    return secret


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def create_token(
    team_id: str,
    set_assigned: str,
    duration_seconds: int = _DEFAULT_DURATION_SECONDS,
) -> str:
    """Create a signed JWT for a team.

    Args:
        team_id: Unique team identifier (e.g. 'TEAM042').
        set_assigned: Question set the team is assigned to ('A', 'B', or 'C').
        duration_seconds: Token lifetime in seconds (default 3 hours).

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "team_id":      team_id,
        "set_assigned": set_assigned,
        "iat":          int(now.timestamp()),
        "exp":          int((now + timedelta(seconds=duration_seconds)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def verify_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT.

    Args:
        token: Raw JWT string (without 'Bearer ' prefix).

    Returns:
        Decoded payload dict.

    Raises:
        jwt.ExpiredSignatureError: Token has expired.
        jwt.InvalidTokenError: Token is malformed or signature is invalid.
    """
    return jwt.decode(token, _secret(), algorithms=["HS256"])


# ---------------------------------------------------------------------------
# PIN helpers
# ---------------------------------------------------------------------------

def hash_pin(pin: str) -> str:
    """Return a bcrypt hash string for the given plaintext PIN.

    Args:
        pin: Plaintext PIN string.

    Returns:
        UTF-8 decoded bcrypt hash suitable for storage.
    """
    return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_pin(pin: str, hashed: str) -> bool:
    """Check a plaintext PIN against a stored bcrypt hash.

    Args:
        pin: Plaintext PIN to check.
        hashed: Stored bcrypt hash string.

    Returns:
        True if the PIN matches, False otherwise.
    """
    try:
        return bcrypt.checkpw(pin.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# @require_auth decorator
# ---------------------------------------------------------------------------

def require_auth(f):
    """Protect a Flask route with JWT bearer authentication.

    Reads the Authorization header, validates the token, and populates:
      - flask.g.team_id      — team identifier from the token
      - flask.g.set_assigned — question set from the token
      - flask.g.token_payload — full decoded payload

    Returns HTTP 401 if the token is missing, expired, or invalid.
    Returns HTTP 403 if the token is valid but the team has already submitted
    (routes that need this check can inspect g.token_payload directly).
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return (
                jsonify({"error": "missing_token", "message": "Authorization header required."}),
                401,
            )

        token = auth_header[len("Bearer "):]
        try:
            payload = verify_token(token)
        except jwt.ExpiredSignatureError:
            return (
                jsonify({"error": "token_expired", "message": "Session has expired."}),
                401,
            )
        except jwt.InvalidTokenError as exc:
            return (
                jsonify({"error": "invalid_token", "message": str(exc)}),
                401,
            )

        g.team_id       = payload["team_id"]
        g.set_assigned  = payload["set_assigned"]
        g.token_payload = payload

        return f(*args, **kwargs)

    return decorated
