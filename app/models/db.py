"""Supabase client singleton.

Usage anywhere in the application:
    from app.models.db import get_supabase
    sb = get_supabase()
    result = sb.table("teams").select("*").execute()
"""
import os
from threading import Lock
from typing import Optional

from supabase import Client, create_client


_client: Optional[Client] = None
_lock: Lock = Lock()


def get_supabase() -> Client:
    """Return the shared Supabase client, creating it on first call.

    Thread-safe via a module-level lock so it is safe under Gunicorn
    multi-threaded workers.

    Returns:
        Authenticated Supabase Client using the service role key.

    Raises:
        EnvironmentError: If SUPABASE_URL or SUPABASE_SERVICE_KEY are missing.
        RuntimeError: If the client cannot be created.
    """
    global _client

    if _client is not None:
        return _client

    with _lock:
        # Double-checked locking
        if _client is not None:
            return _client

        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")

        if not url:
            raise EnvironmentError(
                "SUPABASE_URL environment variable is not set."
            )
        if not key:
            raise EnvironmentError(
                "SUPABASE_SERVICE_KEY environment variable is not set."
            )

        try:
            _client = create_client(url, key)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to create Supabase client: {exc}"
            ) from exc

    return _client


def reset_client() -> None:
    """Reset the singleton (useful in tests to inject a fresh client)."""
    global _client
    with _lock:
        _client = None
