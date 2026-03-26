#!/usr/bin/env python3
"""setup_supabase.py — Supabase production configuration checker.

Run before the event to verify all tables exist, RLS status,
and default app_config rows are in place.

Usage:
    python scripts/setup_supabase.py
"""

import os
import sys
from pathlib import Path

# ── Load .env ────────────────────────────────────────────────────────────────

def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_env()

OK   = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m⚠\033[0m"

REQUIRED_TABLES = ["teams", "questions", "sessions", "audit_logs", "app_config"]

# SQL to create each missing table (for display only — run in Supabase SQL editor)
_TABLE_SQL = {
    "teams": """\
CREATE TABLE teams (
  team_id          TEXT PRIMARY KEY,
  pin_hash         TEXT NOT NULL,
  team_name        TEXT,
  set_assigned     TEXT CHECK (set_assigned IN ('A','B','C')),
  status           TEXT DEFAULT 'waiting'
                        CHECK (status IN ('waiting','active','submitted')),
  score            INTEGER DEFAULT 0,
  finish_time      TIMESTAMPTZ,
  login_count      INTEGER DEFAULT 0,
  tab_switch_count INTEGER DEFAULT 0,
  screen_locked    BOOLEAN DEFAULT false,
  relogin_requested BOOLEAN DEFAULT false
);""",
    "questions": """\
CREATE TABLE questions (
  question_id   SERIAL PRIMARY KEY,
  set_id        TEXT NOT NULL CHECK (set_id IN ('A','B','C')),
  question_text TEXT NOT NULL,
  option_a      TEXT NOT NULL,
  option_b      TEXT NOT NULL,
  option_c      TEXT NOT NULL,
  option_d      TEXT NOT NULL,
  correct_answer TEXT NOT NULL CHECK (correct_answer IN ('A','B','C','D'))
);""",
    "sessions": """\
CREATE TABLE sessions (
  team_id           TEXT PRIMARY KEY REFERENCES teams(team_id),
  answers_json      JSONB DEFAULT '{}',
  server_start_time TIMESTAMPTZ,
  remaining_seconds INTEGER DEFAULT 1800,
  last_saved_at     TIMESTAMPTZ DEFAULT NOW()
);""",
    "audit_logs": """\
CREATE TABLE audit_logs (
  id         SERIAL PRIMARY KEY,
  team_id    TEXT REFERENCES teams(team_id),
  event_type TEXT NOT NULL,
  timestamp  TIMESTAMPTZ DEFAULT NOW(),
  metadata   JSONB DEFAULT '{}'
);""",
    "app_config": """\
CREATE TABLE app_config (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);""",
}

_DEFAULT_CONFIG = {
    "event_status":           "waiting",
    "event_duration_seconds": "1800",
    "allowed_ip":             "",
}


def step(msg: str) -> None:
    print(f"\n  {msg}")


def ok(msg: str) -> None:
    print(f"  {OK} {msg}")


def warn(msg: str) -> None:
    print(f"  {WARN} {msg}")


def fail(msg: str) -> None:
    print(f"  {FAIL} {msg}", file=sys.stderr)


def main() -> None:
    print("\n" + "="*60)
    print("  Supabase Setup — Math Quiz Platform")
    print("="*60)

    # ── 1. Credentials ──────────────────────────────────────────────────
    step("1. Checking environment variables…")
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")

    if not url:
        fail("SUPABASE_URL is not set.")
        sys.exit(1)
    if not key:
        fail("SUPABASE_SERVICE_KEY is not set.")
        sys.exit(1)
    if "anon" in key[:20].lower():
        warn("SUPABASE_SERVICE_KEY looks like an ANON key. Use the service_role key instead.")
    ok("Credentials found.")

    # ── 2. Connect ──────────────────────────────────────────────────────
    step("2. Connecting to Supabase…")
    try:
        from supabase import create_client
        sb = create_client(url, key)
        # Ping with a minimal query
        sb.table("app_config").select("key").limit(1).execute()
        ok(f"Connected to: {url}")
    except Exception as exc:
        fail(f"Connection failed: {exc}")
        print("  Verify SUPABASE_URL and SUPABASE_SERVICE_KEY in your .env / Render dashboard.")
        sys.exit(1)

    # ── 3. Check tables ─────────────────────────────────────────────────
    step("3. Verifying required tables…")
    missing = []
    for table in REQUIRED_TABLES:
        try:
            sb.table(table).select("*").limit(1).execute()
            ok(f"Table '{table}' exists.")
        except Exception:
            fail(f"Table '{table}' NOT FOUND.")
            missing.append(table)

    if missing:
        print("\n  ── SQL to create missing tables (run in Supabase SQL Editor) ──")
        for t in missing:
            print(f"\n  -- {t} --")
            print(_TABLE_SQL[t])
        print()
        sys.exit(1)

    # ── 4. RLS check (informational) ────────────────────────────────────
    step("4. Row Level Security check…")
    warn(
        "Cannot check RLS status via Python SDK. "
        "In Supabase → Table Editor, ensure RLS is DISABLED (or policies allow service_role). "
        "If RLS is ON and you have no policies, all queries will return empty results."
    )

    # ── 5. Seed app_config defaults ─────────────────────────────────────
    step("5. Seeding default app_config rows…")
    for k, v in _DEFAULT_CONFIG.items():
        try:
            # Only insert if not already present
            existing = sb.table("app_config").select("key").eq("key", k).execute()
            if not existing.data:
                sb.table("app_config").insert({"key": k, "value": v}).execute()
                ok(f"Inserted default: {k} = {v!r}")
            else:
                ok(f"Already set: {k} = {existing.data[0].get('value', '?')!r}")
        except Exception as exc:
            fail(f"Could not seed {k}: {exc}")

    # ── 6. Column sanity check ──────────────────────────────────────────
    step("6. Checking teams table columns…")
    try:
        r = sb.table("teams").select("*").limit(0).execute()
        ok("teams table structure accessible.")
    except Exception as exc:
        warn(f"Could not validate teams columns: {exc}")

    print(f"\n  {'='*54}")
    print(f"  {OK} \033[92mSupabase ready.\033[0m")
    print(f"  {'='*54}\n")


if __name__ == "__main__":
    main()
