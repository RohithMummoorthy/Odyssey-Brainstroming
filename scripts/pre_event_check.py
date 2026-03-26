#!/usr/bin/env python3
"""pre_event_check.py — Pre-event system validation checklist (12 checks).

Usage:
    python scripts/pre_event_check.py --url https://your-app.onrender.com

Prints PASS ✓ or FAIL ✗ for each check with exact fix instructions.
Exit code 0 = all pass, 1 = one or more failed.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ── Load .env ────────────────────────────────────────────────────────────────

def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_env()

# ── Styling ───────────────────────────────────────────────────────────────────

_PASS = "\033[92m✓ PASS\033[0m"
_FAIL = "\033[91m✗ FAIL\033[0m"
_SKIP = "\033[93m⚠ SKIP\033[0m"

_results: list[tuple[str, bool | None, str]] = []  # (label, passed|None=skip, fix)


def record(label: str, passed: bool, fix: str = "") -> None:
    tag = _PASS if passed else _FAIL
    icon = "  " if passed else "→ "
    print(f"  [{tag}] {label}")
    if not passed and fix:
        print(f"  {icon}FIX: {fix}")
    _results.append((label, passed, fix))


def skip(label: str, reason: str) -> None:
    print(f"  [{_SKIP}] {label} — {reason}")
    _results.append((label, None, ""))


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _http(method: str, url: str, body: dict | None = None,
          headers: dict | None = None, timeout: int = 15):
    headers = headers or {"Content-Type": "application/json"}
    data    = json.dumps(body).encode() if body else None
    req     = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body_text)
        except Exception:
            return exc.code, {"_raw": body_text}
    except Exception as exc:
        return 0, {"_error": str(exc)}


# ── Supabase helper ───────────────────────────────────────────────────────────

_sb = None

def _get_sb():
    global _sb
    if _sb is None:
        from supabase import create_client
        _sb = create_client(
            os.getenv("SUPABASE_URL", ""),
            os.getenv("SUPABASE_SERVICE_KEY", ""),
        )
    return _sb


# ── Individual checks ─────────────────────────────────────────────────────────

def check_1_health(base_url: str) -> None:
    label = f"GET {base_url}/health → 200"
    status, data = _http("GET", f"{base_url}/health")
    record(label, status == 200 and data.get("status") == "ok",
           "App is not reachable. Check Render deploy logs. Free tier may be sleeping — open the URL manually to wake it.")


def check_2_teams_exist() -> None:
    label = "Supabase: teams table has rows"
    try:
        r = _get_sb().table("teams").select("team_id").execute()
        n = len(r.data or [])
        record(label, n > 0,
               f"Run: python scripts/generate_credentials.py  ({n} teams found)")
    except Exception as exc:
        record(label, False, f"DB error: {exc}")


def check_3_questions_count() -> None:
    label = "Supabase: questions table has >= 90 rows"
    try:
        r = _get_sb().table("questions").select("id").execute()
        n = len(r.data or [])
        record(label, n >= 90,
               f"Run: python scripts/upload_questions.py  (found {n}, need 90)")
    except Exception as exc:
        record(label, False, f"DB error: {exc}")


def check_4_questions_per_set() -> None:
    for set_id in ("A", "B", "C"):
        label = f"Supabase: set {set_id} has >= 30 questions"
        try:
            r = _get_sb().table("questions").select("id").eq("set_id", set_id).execute()
            n = len(r.data or [])
            record(label, n >= 30,
                   f"Run: python scripts/upload_questions.py  (found {n} for set {set_id})")
        except Exception as exc:
            record(label, False, f"DB error: {exc}")


def check_5_event_status_waiting() -> None:
    label = "Supabase: event_status = 'waiting'"
    try:
        r = _get_sb().table("app_config").select("value").eq("key", "event_status").single().execute()
        v = (r.data or {}).get("value", "")
        record(label, v == "waiting",
               f"SQL: UPDATE app_config SET value='waiting' WHERE key='event_status';  (current: {v!r})")
    except Exception as exc:
        record(label, False, f"DB error: {exc}")


def check_6_ip_not_locked() -> None:
    label = "Supabase: allowed_ip = '' (not pre-locked)"
    try:
        r = _get_sb().table("app_config").select("value").eq("key", "allowed_ip").single().execute()
        v = (r.data or {}).get("value", "")
        record(label, v == "",
               f"SQL: UPDATE app_config SET value='' WHERE key='allowed_ip';  (current: {v!r})")
    except Exception as exc:
        record(label, False, f"DB error: {exc}")


def check_7_teams_waiting() -> None:
    label = "Supabase: all teams have status='waiting'"
    try:
        r = _get_sb().table("teams").select("status").execute()
        bad = [t for t in (r.data or []) if t.get("status") != "waiting"]
        record(label, not bad,
               f"{len(bad)} teams not 'waiting'. SQL: UPDATE teams SET status='waiting', score=0, finish_time=NULL;")
    except Exception as exc:
        record(label, False, f"DB error: {exc}")


def check_8_sessions_empty() -> None:
    label = "Supabase: sessions table is empty (clean state)"
    try:
        r = _get_sb().table("sessions").select("team_id").execute()
        n = len(r.data or [])
        record(label, n == 0,
               f"SQL: DELETE FROM sessions;  ({n} sessions found)")
    except Exception as exc:
        record(label, False, f"DB error: {exc}")


def check_9_admin_login(base_url: str) -> None:
    label = f"POST {base_url}/admin/login with ADMIN_PASSWORD → 200"
    admin_pw = os.getenv("ADMIN_PASSWORD", "")
    if not admin_pw:
        skip(label, "ADMIN_PASSWORD not set locally")
        return
    status, data = _http("POST", f"{base_url}/admin/login", {"password": admin_pw})
    record(label, status == 200 and "token" in data,
           "ADMIN_PASSWORD mismatch. Check value in Render env vars.")


def check_10_google_sheets() -> None:
    label = "Google Sheets: connection works"
    creds_json = os.getenv("GOOGLE_CREDS_JSON", "")
    sheet_id   = os.getenv("GOOGLE_SHEET_ID", "")
    if not creds_json or not sheet_id:
        skip(label, "GOOGLE_CREDS_JSON or GOOGLE_SHEET_ID not set")
        return
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_dict = json.loads(creds_json)
        scopes = ["https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
        creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc     = gspread.authorize(creds)
        wb     = gc.open_by_key(sheet_id)
        # Write+delete test row
        ws   = wb.sheet1
        ws.append_row(["PRE_CHECK_TEST"])
        n = len(ws.get_all_values())
        ws.delete_rows(n)
        record(label, True)
    except Exception as exc:
        record(label, False,
               f"Follow GOOGLE_SETUP.md. Error: {exc}")


def check_11_auth_rejects_fake(base_url: str) -> None:
    label = f"POST {base_url}/login with fake creds → 401 (not 500)"
    status, data = _http("POST", f"{base_url}/login",
                         {"team_id": "FAKE_TEAM_00000", "pin": "0000"})
    record(label, status == 401,
           f"Expected 401, got {status}. Check /login route error handling.")


def check_12_leaderboard_public(base_url: str) -> None:
    label = f"GET {base_url}/leaderboard → 200 (no auth)"
    status, _ = _http("GET", f"{base_url}/leaderboard")
    record(label, status == 200,
           "Leaderboard route not reachable. Check leaderboard blueprint is registered.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Pre-event system checker")
    p.add_argument("--url", "--render-url",
                   default=os.getenv("RENDER_URL", ""),
                   help="Render deployment URL (e.g. https://math-quiz.onrender.com)")
    p.add_argument("--expected-teams", type=int, default=10,
                   help="Minimum expected team count (default 10)")
    args = p.parse_args()

    base_url = args.url.rstrip("/")

    print("\n" + "═"*60)
    print("  Math Quiz Platform — Pre-Event Checklist")
    print("═"*60 + "\n")

    if base_url:
        print(f"  Target: {base_url}\n")
        check_1_health(base_url)
    else:
        skip("Health check", "pass --url to enable live checks")

    print()

    # Supabase checks
    supabase_ok = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY"))
    if supabase_ok:
        check_2_teams_exist()
        check_3_questions_count()
        check_4_questions_per_set()
        check_5_event_status_waiting()
        check_6_ip_not_locked()
        check_7_teams_waiting()
        check_8_sessions_empty()
    else:
        print(f"  [{_SKIP}] Supabase checks — SUPABASE_URL/SUPABASE_SERVICE_KEY not set locally")

    print()
    check_10_google_sheets()

    if base_url:
        print()
        check_9_admin_login(base_url)
        check_11_auth_rejects_fake(base_url)
        check_12_leaderboard_public(base_url)

    # ── Summary ───────────────────────────────────────────────────────
    ran    = [(l, p, f) for l, p, f in _results if p is not None]
    passed = sum(1 for _, p, _ in ran if p)
    failed = len(ran) - passed

    print(f"\n{'═'*60}")
    if failed == 0:
        print("\033[92m")
        print("  ██████╗  ██████╗ ██╗")
        print("  ██╔════╝ ██╔═══██╗██║")
        print("  ██║  ███╗██║   ██║██║")
        print("  ██║   ██║██║   ██║╚═╝")
        print("  ╚██████╔╝╚██████╔╝██╗")
        print("   ╚═════╝  ╚═════╝ ╚═╝")
        print("\033[0m")
        print(f"  ✓ SYSTEM READY. GO RUN YOUR EVENT.  ({passed}/{len(ran)} checks passed)")
    else:
        print(f"\033[91m  ✗ {failed} check(s) FAILED — fix before event day.\033[0m")
        print(f"     {passed}/{len(ran)} passed")
    print("═"*60 + "\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
