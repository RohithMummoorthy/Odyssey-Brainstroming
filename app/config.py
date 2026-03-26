"""Application configuration — loads all required environment variables.

Safe defaults are provided for all optional values so the app never
crashes on import due to a missing env var.  Only SUPABASE_URL and
SUPABASE_SERVICE_KEY are strictly required at runtime (Supabase client
will error if they are empty).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file)
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


class Config:
    """Base configuration shared across all environments."""

    # ── Supabase ───────────────────────────────────────────────────────────
    SUPABASE_URL: str         = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

    # ── Security ───────────────────────────────────────────────────────────
    # JWT_SECRET falls back to a build-time warning value — Render will
    # auto-generate a real one via generateValue: true in render.yaml.
    JWT_SECRET: str  = os.getenv("JWT_SECRET", "CHANGE_THIS_IN_PRODUCTION")
    SECRET_KEY: str  = JWT_SECRET           # Flask session key alias
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")

    # ── Event timing ───────────────────────────────────────────────────────
    EVENT_DURATION_SECONDS: int = int(os.getenv("EVENT_DURATION_SECONDS", "1800"))

    # ── Google Sheets (optional) ───────────────────────────────────────────
    GOOGLE_SHEET_ID:   str = os.getenv("GOOGLE_SHEET_ID", "")
    GOOGLE_CREDS_JSON: str = os.getenv("GOOGLE_CREDS_JSON", "")

    # ── Flask internals ────────────────────────────────────────────────────
    DEBUG: bool   = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    TESTING: bool = False


class TestingConfig(Config):
    """Config used by pytest — never touches real Supabase."""
    TESTING: bool  = True
    DEBUG: bool    = True
    JWT_SECRET: str     = "test-secret-do-not-use-in-production"
    SECRET_KEY: str     = JWT_SECRET
    ADMIN_PASSWORD: str = "test-admin-password"
    SUPABASE_URL: str         = "https://placeholder.supabase.co"
    SUPABASE_SERVICE_KEY: str = "placeholder-service-key"


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
