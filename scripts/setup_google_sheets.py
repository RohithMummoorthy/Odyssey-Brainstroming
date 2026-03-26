#!/usr/bin/env python3
"""setup_google_sheets.py — Google Sheets setup and validation.

Run before the event to verify Sheets connectivity and pre-create the
"Results" and "Audit Logs" tabs with correct headers.

Usage:
    python scripts/setup_google_sheets.py
"""

import json
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

# ── Helpers ───────────────────────────────────────────────────────────────────

OK   = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"

def step(msg: str) -> None:
    print(f"\n  {msg}")

def ok(msg: str) -> None:
    print(f"  {OK} {msg}")

def fail(msg: str) -> None:
    print(f"  {FAIL} {msg}", file=sys.stderr)

# ── Headers ───────────────────────────────────────────────────────────────────

RESULTS_HEADERS = [
    "Rank", "Team ID", "Team Name", "Score", "Questions Answered",
    "Finish Time", "Time Taken (min)", "Tab Switches", "Set Assigned", "Status",
]

AUDIT_HEADERS = ["Team ID", "Event Type", "Timestamp", "Metadata"]

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n" + "="*60)
    print("  Google Sheets Setup — Math Quiz Platform")
    print("="*60)

    # ── 1. Check GOOGLE_CREDS_JSON ─────────────────────────────────────
    step("1. Validating GOOGLE_CREDS_JSON…")
    creds_json = os.getenv("GOOGLE_CREDS_JSON", "")
    if not creds_json:
        fail("GOOGLE_CREDS_JSON is not set.")
        print("""
  How to fix:
    1. Go to console.cloud.google.com
    2. Create project → Enable 'Google Sheets API' + 'Google Drive API'
    3. IAM & Admin → Service Accounts → Create Service Account
    4. Create Key → JSON → Download
    5. Set GOOGLE_CREDS_JSON to the ENTIRE file content (one line in .env)
""")
        sys.exit(1)

    try:
        creds_dict = json.loads(creds_json)
        client_email = creds_dict.get("client_email", "")
        ok(f"GOOGLE_CREDS_JSON is valid JSON (service account: {client_email})")
    except json.JSONDecodeError as exc:
        fail(f"GOOGLE_CREDS_JSON is not valid JSON: {exc}")
        print("  Hint: make sure the entire file content is on a single line with no extra quoting.")
        sys.exit(1)

    # ── 2. Check GOOGLE_SHEET_ID ───────────────────────────────────────
    step("2. Checking GOOGLE_SHEET_ID…")
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if not sheet_id:
        fail("GOOGLE_SHEET_ID is not set.")
        print("  Hint: copy the ID from the sheet URL: https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit")
        sys.exit(1)
    ok(f"GOOGLE_SHEET_ID = {sheet_id}")

    # ── 3. Authenticate ────────────────────────────────────────────────
    step("3. Authenticating with Google Sheets API…")
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc     = gspread.authorize(creds)
        ok("Authentication successful.")
    except ImportError:
        fail("gspread / google-auth not installed. Run: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as exc:
        fail(f"Authentication failed: {exc}")
        sys.exit(1)

    # ── 4. Open spreadsheet ────────────────────────────────────────────
    step("4. Opening spreadsheet…")
    try:
        workbook = gc.open_by_key(sheet_id)
        ok(f"Opened: '{workbook.title}'")
    except gspread.exceptions.SpreadsheetNotFound:
        fail(f"Spreadsheet not found. Make sure you shared it with: {creds_dict.get('client_email')}")
        print("  Go to Google Sheets → Share → add the service account email as Editor.")
        sys.exit(1)
    except Exception as exc:
        fail(f"Could not open spreadsheet: {exc}")
        sys.exit(1)

    # ── 5. Create / update Results sheet ──────────────────────────────
    step("5. Setting up 'Sheet1' (Results) tab…")
    try:
        sheet1 = workbook.sheet1
        sheet1.clear()
        sheet1.update([RESULTS_HEADERS], "A1")
        sheet1.format("A1:J1", {"textFormat": {"bold": True}})
        sheet1.freeze(rows=1)
        ok(f"Results tab ready ({len(RESULTS_HEADERS)} columns, header bolded, row frozen).")
    except Exception as exc:
        fail(f"Could not set up Results tab: {exc}")
        sys.exit(1)

    # ── 6. Create / update Audit Logs sheet ──────────────────────────
    step("6. Setting up 'Audit Logs' tab…")
    try:
        try:
            audit_ws = workbook.worksheet("Audit Logs")
        except gspread.exceptions.WorksheetNotFound:
            audit_ws = workbook.add_worksheet(title="Audit Logs", rows="1000", cols="10")
        audit_ws.clear()
        audit_ws.update([AUDIT_HEADERS], "A1")
        audit_ws.format("A1:D1", {"textFormat": {"bold": True}})
        ok("Audit Logs tab ready.")
    except Exception as exc:
        fail(f"Could not set up Audit Logs tab: {exc}")
        sys.exit(1)

    # ── 7. Write + delete test row ─────────────────────────────────────
    step("7. Write/delete test row to verify write access…")
    try:
        sheet1.append_row(["SETUP_TEST", "—", "—", "—", "—", "—", "—", "—", "—", "—"])
        nrows = len(sheet1.get_all_values())
        sheet1.delete_rows(nrows)
        ok("Write and delete confirmed.")
    except Exception as exc:
        fail(f"Write test failed: {exc}")
        sys.exit(1)

    print(f"\n  {'='*54}")
    print(f"  {OK} \033[92mGoogle Sheets ready.\033[0m")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    print(f"     Sheet URL: {sheet_url}")
    print(f"  {'='*54}\n")


if __name__ == "__main__":
    main()
