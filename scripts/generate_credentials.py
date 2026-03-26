#!/usr/bin/env python3
"""Generate 500 team credentials and upload them to Supabase.

Output:
  - Inserts 500 rows into the `teams` table (bcrypt-hashed PINs).
  - Writes credentials.csv with plaintext team_id + PIN for printing.

Usage:
    python scripts/generate_credentials.py
"""
import csv
import os
import random
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import bcrypt

from app.models.db import get_supabase

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# To increase the total allowed teams in the future, simply change this
# number to 500 (or anything) and then safely re-run this script!
NUM_TEAMS = 200
PIN_LENGTH = 6
PIN_CHARS = string.ascii_uppercase + string.digits   # A-Z 0-9
CSV_PATH = Path(__file__).resolve().parent.parent / "credentials.csv"
BATCH_SIZE = 50   # rows per Supabase upsert call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def generate_pin() -> str:
    """Return a random 6-character alphanumeric PIN (uppercase)."""
    return "".join(random.choices(PIN_CHARS, k=PIN_LENGTH))


def hash_pin(pin: str) -> str:
    """Return a bcrypt hash for the given PIN string."""
    return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def build_rows(num: int) -> tuple[list[dict], list[dict]]:
    """Build a list of team dicts with hashed PINs, plus plaintext for CSV."""
    rows_db = []       # will go to Supabase
    rows_csv = []      # plaintext — credential sheet for participants

    for i in range(1, num + 1):
        team_id = f"TEAM{i:03d}"
        pin = generate_pin()
        pin_hash = hash_pin(pin)

        rows_db.append(
            {
                "team_id":    team_id,
                "pin_hash":   pin_hash,
                "team_name":  None,
                "status":     "waiting",
                "score":      0,
                "tab_switch_count": 0,
                "login_count":      0,
                "relogin_requested": False,
            }
        )
        rows_csv.append({"team_id": team_id, "pin": pin})

    return rows_db, rows_csv


def upload_to_supabase(sb, rows_db: list[dict]) -> None:
    """Wipe existing teams and upload rows in batches."""
    print("WARNING: Wiping all existing teams from the database to strictly provision the correct count...")
    try:
        sb.table("audit_logs").delete().neq("id", 0).execute()
        sb.table("sessions").delete().neq("team_id", "0").execute()
        sb.table("teams").delete().neq("team_id", "0").execute()
    except Exception as exc:
        print(f"Failed to wipe old data: {exc}")

    print(f"\nUploading {len(rows_db)} teams to Supabase in batches of {BATCH_SIZE}…")
    inserted = 0

    for start in range(0, len(rows_db), BATCH_SIZE):
        batch = rows_db[start : start + BATCH_SIZE]
        try:
            result = (
                sb.table("teams")
                .upsert(batch, on_conflict="team_id")
                .execute()
            )
            inserted += len(batch)
            print(f"  Uploaded rows {start + 1}–{start + len(batch)}")
        except Exception as exc:
            print(
                f"  [ERROR] Batch {start + 1}–{start + len(batch)} failed: {exc}",
                file=sys.stderr,
            )
            raise

    print(f"\n  [OK] {inserted} team rows upserted to Supabase.")


def write_csv(rows_csv: list[dict]) -> None:
    """Write plaintext credentials to CSV."""
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["team_id", "pin"])
        writer.writeheader()
        writer.writerows(rows_csv)
    print(f"\n  [OK] Plaintext credentials saved to: {CSV_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== generate_credentials.py ===")
    print(f"Generating {NUM_TEAMS} team credentials…")

    rows_db, rows_csv = build_rows(NUM_TEAMS)

    print("Connecting to Supabase…")
    sb = get_supabase()

    upload_to_supabase(sb, rows_db)
    write_csv(rows_csv)

    print("\n[DONE] Distribute credentials.csv to participants.")


if __name__ == "__main__":
    main()
