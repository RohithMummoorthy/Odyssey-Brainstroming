#!/usr/bin/env python3
"""Seed the Supabase database.

Creates all required tables and seeds initial app_config values.
Run once before the first deployment:
    python scripts/seed_db.py

Tables created:
    teams, questions, sessions, audit_logs, app_config
"""
import os
import sys
from pathlib import Path

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.models.db import get_supabase


# ---------------------------------------------------------------------------
# SQL DDL
# Each statement is kept separate so we can report errors per-table.
# ---------------------------------------------------------------------------
STATEMENTS = [
    # ── teams ────────────────────────────────────────────────────────────
    (
        "teams",
        """
        CREATE TABLE IF NOT EXISTS teams (
            team_id             TEXT        PRIMARY KEY,
            pin_hash            TEXT        NOT NULL,
            team_name           TEXT,
            set_assigned        TEXT        CHECK (set_assigned IN ('A','B','C')),
            status              TEXT        DEFAULT 'waiting'
                                            CHECK (status IN ('waiting','active','submitted')),
            score               INTEGER     DEFAULT 0,
            finish_time         TIMESTAMPTZ,
            tab_switch_count    INTEGER     DEFAULT 0,
            screen_locked       BOOLEAN     DEFAULT false,
            login_count         INTEGER     DEFAULT 0,
            relogin_requested   BOOLEAN     DEFAULT false,
            created_at          TIMESTAMPTZ DEFAULT now()
        );
        """,
    ),

    # ── questions ────────────────────────────────────────────────────────
    (
        "questions",
        """
        CREATE TABLE IF NOT EXISTS questions (
            id              SERIAL      PRIMARY KEY,
            set_id          TEXT        NOT NULL,
            question_text   TEXT        NOT NULL,
            option_a        TEXT,
            option_b        TEXT,
            option_c        TEXT,
            option_d        TEXT,
            correct_answer  TEXT        CHECK (correct_answer IN ('A','B','C','D')),
            base_order      INTEGER
        );
        """,
    ),

    # ── sessions ─────────────────────────────────────────────────────────
    (
        "sessions",
        """
        CREATE TABLE IF NOT EXISTS sessions (
            team_id             TEXT        PRIMARY KEY REFERENCES teams(team_id),
            answers_json        JSONB       DEFAULT '{}',
            last_saved_at       TIMESTAMPTZ DEFAULT now(),
            server_start_time   TIMESTAMPTZ,
            remaining_seconds   INTEGER     DEFAULT 1800
        );
        """,
    ),

    # ── audit_logs ───────────────────────────────────────────────────────
    (
        "audit_logs",
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id          SERIAL      PRIMARY KEY,
            team_id     TEXT        REFERENCES teams(team_id),
            event_type  TEXT,
            timestamp   TIMESTAMPTZ DEFAULT now(),
            metadata    JSONB
        );
        """,
    ),

    # ── app_config ───────────────────────────────────────────────────────
    (
        "app_config",
        """
        CREATE TABLE IF NOT EXISTS app_config (
            key     TEXT PRIMARY KEY,
            value   TEXT
        );
        """,
    ),
]

APP_CONFIG_SEED = [
    ("allowed_ip",              ""),
    ("event_status",            "waiting"),
    ("event_duration_seconds",  "1800"),
]


def run_sql(sb, label: str, sql: str) -> None:
    """Execute a raw SQL statement via Supabase RPC and report status."""
    try:
        sb.rpc("exec_sql", {"query": sql}).execute()
        print(f"  ✓  {label}")
    except Exception as exc:
        # Supabase Python client v2 exposes raw PostgreSQL errors.
        # Provide a helpful message and re-raise so the caller can decide.
        print(f"  ✗  {label} — {exc}", file=sys.stderr)
        raise


def create_tables(sb) -> None:
    """Create all tables using Supabase's postgrest RPC.

    NOTE: Supabase does not expose raw SQL execution through the REST API by
    default. The recommended approach is to use the Supabase Management API
    or run migrations through the dashboard / CLI.

    As a practical workaround for scripts like this, we attempt to use an
    `exec_sql` RPC function if one exists, otherwise we print the SQL so the
    operator can run it manually.
    """
    print("\n=== Creating tables ===")
    for label, sql in STATEMENTS:
        try:
            run_sql(sb, label, sql.strip())
        except Exception:
            # If exec_sql RPC is not available, print and continue
            print(
                f"     → Could not execute via RPC. Run the following SQL "
                f"manually in the Supabase SQL editor:\n{sql.strip()}\n",
                file=sys.stderr,
            )


def seed_app_config(sb) -> None:
    """Insert seed rows into app_config (upsert — safe to re-run)."""
    print("\n=== Seeding app_config ===")
    rows = [{"key": k, "value": v} for k, v in APP_CONFIG_SEED]
    try:
        result = (
            sb.table("app_config")
            .upsert(rows, on_conflict="key")
            .execute()
        )
        print(f"  ✓  {len(rows)} config rows upserted")
    except Exception as exc:
        print(f"  ✗  app_config seed failed — {exc}", file=sys.stderr)
        print(
            "     → The 'app_config' table does not exist yet.\n"
            "       Paste the MANUAL SQL above into Supabase → SQL Editor,\n"
            "       then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)


def print_manual_sql() -> None:
    """Print all DDL to stdout so operators can run it in the Supabase SQL editor."""
    print("\n" + "=" * 60)
    print("MANUAL SQL (paste into Supabase → SQL Editor if RPC fails)")
    print("=" * 60)
    for label, sql in STATEMENTS:
        print(f"\n-- {label}")
        print(sql.strip())

    print("\n-- app_config seed")
    for key, val in APP_CONFIG_SEED:
        print(
            f"INSERT INTO app_config (key, value) VALUES ('{key}', '{val}') "
            f"ON CONFLICT (key) DO NOTHING;"
        )
    print("=" * 60 + "\n")


def main() -> None:
    print("Connecting to Supabase…")
    sb = get_supabase()
    print("Connected.\n")

    # Always print the SQL so operators can run it manually if needed
    print_manual_sql()

    # Attempt programmatic execution
    create_tables(sb)
    seed_app_config(sb)

    print("\n✅  seed_db completed.")


if __name__ == "__main__":
    main()
