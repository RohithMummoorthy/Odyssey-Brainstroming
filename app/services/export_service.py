"""export_service.py — Google Sheets export for Math Quiz Platform.

Functions:
    export_results_to_sheet()    — writes team results to Sheet1
    export_audit_logs_to_sheet() — writes audit events to "Audit Logs" tab

Authentication: GOOGLE_CREDS_JSON env var (full service account JSON string).
Sheet:          GOOGLE_SHEET_ID env var.
"""
import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# ── Column headers ─────────────────────────────────────────────────────────

_RESULTS_HEADERS = [
    "Rank", "Team ID", "Team Name", "Score", "Questions Answered",
    "Finish Time", "Time Taken (min)", "Tab Switches", "Set Assigned", "Status",
]

_AUDIT_HEADERS = ["Team ID", "Event Type", "Timestamp", "Metadata"]


# ── Auth helper ────────────────────────────────────────────────────────────

def _get_gspread_client():
    """Authenticate via service account and return a gspread Client."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    if not creds_json:
        raise EnvironmentError("GOOGLE_CREDS_JSON environment variable is not set.")

    creds_dict = json.loads(creds_json)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


def _open_sheet(client, tab_title: str | None = None):
    """Open the spreadsheet and return the requested worksheet."""
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise EnvironmentError("GOOGLE_SHEET_ID environment variable is not set.")

    workbook = client.open_by_key(sheet_id)

    if tab_title is None:
        return workbook.sheet1, workbook

    # Create or fetch named worksheet
    try:
        ws = workbook.worksheet(tab_title)
    except Exception:
        ws = workbook.add_worksheet(title=tab_title, rows="500", cols="20")

    return ws, workbook


# ── Results export ─────────────────────────────────────────────────────────

def export_results_to_sheet() -> dict:
    """Write all team results to Sheet1 of the configured Google Sheet.

    Returns:
        {"rows_written": int, "sheet_url": str}
    """
    from app.models.db import get_supabase
    sb = get_supabase()

    # ── Fetch teams ────────────────────────────────────────────────────
    teams_r = sb.table("teams").select(
        "team_id,team_name,status,score,finish_time,tab_switch_count,set_assigned"
    ).order("score", desc=True).execute()
    teams = teams_r.data or []

    # Sort: score desc, then finish_time asc
    def _sort_key(t):
        ft = t.get("finish_time") or "9999"
        return (-(t.get("score") or 0), ft)

    teams.sort(key=_sort_key)

    # ── Fetch sessions for questions_answered ──────────────────────────
    sess_r = sb.table("sessions").select("team_id,answers_json,server_start_time").execute()
    sessions = {s["team_id"]: s for s in (sess_r.data or [])}

    # ── Build rows ─────────────────────────────────────────────────────
    rows = [_RESULTS_HEADERS]
    for rank, team in enumerate(teams, start=1):
        tid  = team["team_id"]
        sess = sessions.get(tid, {})

        answers_json       = sess.get("answers_json") or {}
        questions_answered = sum(1 for v in answers_json.values() if v)

        finish_time = team.get("finish_time")
        start_time  = sess.get("server_start_time")
        time_taken  = ""
        if finish_time and start_time:
            try:
                ft = datetime.fromisoformat(finish_time.replace("Z", "+00:00"))
                st = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                time_taken = round((ft - st).total_seconds() / 60, 2)
            except Exception:
                time_taken = ""

        rows.append([
            rank,
            tid,
            team.get("team_name") or "",
            team.get("score") or 0,
            questions_answered,
            finish_time or "",
            time_taken,
            team.get("tab_switch_count") or 0,
            team.get("set_assigned") or "",
            team.get("status") or "",
        ])

    # ── Write to sheet ─────────────────────────────────────────────────
    client  = _get_gspread_client()
    ws, wb  = _open_sheet(client)

    ws.clear()
    ws.update(rows, "A1")

    # Bold the header row
    try:
        ws.format("A1:J1", {"textFormat": {"bold": True}})
    except Exception as exc:
        log.warning("export_results: could not bold header: %s", exc)

    # Freeze header row
    try:
        ws.freeze(rows=1)
    except Exception:
        pass

    sheet_id  = os.getenv("GOOGLE_SHEET_ID")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    data_rows = len(rows) - 1   # exclude header
    log.info("export_results_to_sheet: wrote %d rows", data_rows)
    return {"rows_written": data_rows, "sheet_url": sheet_url}


# ── Audit log export ───────────────────────────────────────────────────────

def export_audit_logs_to_sheet() -> dict:
    """Write audit_logs to an 'Audit Logs' tab.

    Returns:
        {"rows_written": int, "sheet_url": str}
    """
    from app.models.db import get_supabase
    sb = get_supabase()

    logs_r = (
        sb.table("audit_logs")
        .select("team_id,event_type,timestamp,metadata")
        .order("timestamp", desc=False)
        .execute()
    )
    logs = logs_r.data or []

    rows = [_AUDIT_HEADERS]
    for entry in logs:
        rows.append([
            entry.get("team_id") or "",
            entry.get("event_type") or "",
            entry.get("timestamp") or "",
            json.dumps(entry.get("metadata") or {}),
        ])

    client = _get_gspread_client()
    ws, wb = _open_sheet(client, tab_title="Audit Logs")
    ws.clear()
    ws.update(rows, "A1")

    try:
        ws.format("A1:D1", {"textFormat": {"bold": True}})
    except Exception:
        pass

    sheet_id  = os.getenv("GOOGLE_SHEET_ID")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    data_rows = len(rows) - 1
    log.info("export_audit_logs_to_sheet: wrote %d rows", data_rows)
    return {"rows_written": data_rows, "sheet_url": sheet_url}
