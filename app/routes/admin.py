"""Admin routes blueprint — full Phase 5 implementation.

Auth:
  POST /admin/login           → admin JWT ({role:'admin'})
  All other /admin/* routes   → @require_admin (verifies admin JWT)

Endpoints:
  GET  /admin/status
  POST /admin/lock-network
  POST /admin/unlock-network
  POST /admin/start-event
  POST /admin/end-event
  POST /admin/unlock-screen
  POST /admin/approve-relogin
  POST /admin/force-submit
  GET  /admin/leaderboard
  GET  /admin/audit-logs
  GET  /admin/export-preview
  POST /admin/export-sheets
"""
import functools
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any

import jwt
from flask import Blueprint, g, jsonify, request

from app.models.db import get_supabase
from app.middleware import clear_ip_cache, get_client_ip

log = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__)

_ADMIN_TOKEN_DURATION = 8 * 60 * 60   # 8 hours


# ---------------------------------------------------------------------------
# Admin JWT helpers
# ---------------------------------------------------------------------------

def _secret() -> str:
    s = os.getenv("JWT_SECRET")
    if not s:
        raise EnvironmentError("JWT_SECRET not set")
    return s


def _create_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "role": "admin",
        "iat":  int(now.timestamp()),
        "exp":  int((now + timedelta(seconds=_ADMIN_TOKEN_DURATION)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def _verify_admin_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    if payload.get("role") != "admin":
        raise jwt.InvalidTokenError("Not an admin token")
    return payload


# ---------------------------------------------------------------------------
# @require_admin decorator
# ---------------------------------------------------------------------------

def require_admin(f):
    """Verify admin JWT from Authorization: Bearer <token> header."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "unauthorized", "message": "Admin token required."}), 401
        token = auth[len("Bearer "):]
        try:
            g.admin_payload = _verify_admin_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "token_expired", "message": "Admin session expired."}), 401
        except jwt.InvalidTokenError as exc:
            return jsonify({"error": "unauthorized", "message": str(exc)}), 401
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sb():
    return get_supabase()


def _set_app_config(key: str, value: str) -> None:
    _sb().table("app_config").upsert({"key": key, "value": value}, on_conflict="key").execute()


def _get_app_config(key: str, default: str = "") -> str:
    try:
        r = _sb().table("app_config").select("value").eq("key", key).single().execute()
        return (r.data or {}).get("value", default)
    except Exception:
        return default


def _audit(team_id: str | None, event_type: str, metadata: dict | None = None) -> None:
    try:
        _sb().table("audit_logs").insert(
            {"team_id": team_id, "event_type": event_type, "metadata": metadata or {}}
        ).execute()
    except Exception as exc:
        log.warning("admin audit log failed: %s", exc)


# ---------------------------------------------------------------------------
# POST /admin/login
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/login", methods=["POST"])
def admin_login():
    """Return an admin JWT if the password matches ADMIN_PASSWORD."""
    body     = request.get_json(silent=True) or {}
    password = body.get("password", "")

    admin_pw = os.getenv("ADMIN_PASSWORD", "")
    if not admin_pw or password != admin_pw:
        return jsonify({"error": "unauthorized", "message": "Invalid admin password."}), 401

    token = _create_admin_token()
    return jsonify({"token": token, "expires_in": _ADMIN_TOKEN_DURATION}), 200


# ---------------------------------------------------------------------------
# GET /admin/status
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/status")
@require_admin
def admin_status():
    """Return all teams with session metadata, sorted by completion status."""
    sb = _sb()

    # Fetch teams
    teams_r = sb.table("teams").select(
        "team_id,team_name,status,score,tab_switch_count,screen_locked,"
        "relogin_requested,finish_time,set_assigned,login_count"
    ).execute()
    teams = {t["team_id"]: t for t in (teams_r.data or [])}

    # Fetch sessions for last_saved_at + answers_json
    sess_r = sb.table("sessions").select(
        "team_id,answers_json,last_saved_at"
    ).execute()
    sessions = {s["team_id"]: s for s in (sess_r.data or [])}

    rows = []
    for tid, team in teams.items():
        sess  = sessions.get(tid, {})
        answers_json = sess.get("answers_json") or {}
        questions_answered = sum(1 for v in answers_json.values() if v)

        rows.append({
            "team_id":           tid,
            "team_name":         team.get("team_name") or "",
            "status":            team.get("status") or "waiting",
            "score":             team.get("score") or 0,
            "questions_answered": questions_answered,
            "tab_switch_count":  team.get("tab_switch_count") or 0,
            "screen_locked":     bool(team.get("screen_locked")),
            "relogin_requested": bool(team.get("relogin_requested")),
            "finish_time":       team.get("finish_time"),
            "set_assigned":      team.get("set_assigned") or "",
            "last_saved_at":     sess.get("last_saved_at"),
        })

    # Sort: submitted (score desc, finish_time asc) → active → waiting
    def _sort_key(r):
        status_order = {"submitted": 0, "active": 1, "waiting": 2}
        s = status_order.get(r["status"], 9)
        score = -(r["score"] or 0)
        ft    = r["finish_time"] or "9999"
        return (s, score, ft)

    rows.sort(key=_sort_key)
    return jsonify(rows), 200


# ---------------------------------------------------------------------------
# POST /admin/lock-network
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/lock-network", methods=["POST"])
@require_admin
def lock_network():
    """Lock quiz access to the admin's current IP."""
    ip = get_client_ip()
    if not ip:
        return jsonify({"error": "bad_request", "message": "Could not detect IP."}), 400

    _set_app_config("allowed_ip", ip)
    clear_ip_cache()
    _audit(None, "network_locked", {"ip": ip})
    log.info("Network locked to %s", ip)
    return jsonify({"locked_to": ip}), 200


# ---------------------------------------------------------------------------
# POST /admin/unlock-network
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/unlock-network", methods=["POST"])
@require_admin
def unlock_network():
    """Remove IP restriction."""
    _set_app_config("allowed_ip", "")
    clear_ip_cache()
    _audit(None, "network_unlocked")
    return jsonify({"unlocked": True}), 200


# ---------------------------------------------------------------------------
# POST /admin/start-event
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/start-event", methods=["POST"])
@require_admin
def start_event():
    """Set event_status=running and activate all waiting teams."""
    sb = _sb()
    _set_app_config("event_status", "running")

    # Find waiting teams
    teams_r = sb.table("teams").select("team_id").eq("status", "waiting").execute()
    waiting_teams = [t["team_id"] for t in (teams_r.data or [])]
    now_utc = datetime.now(timezone.utc).isoformat()

    updated = 0
    for tid in waiting_teams:
        try:
            sb.table("teams").update({"status": "active"}).eq("team_id", tid).execute()
            # Upsert session with server_start_time
            sb.table("sessions").upsert(
                {
                    "team_id":           tid,
                    "server_start_time": now_utc,
                    "answers_json":      {},
                    "remaining_seconds": int(_get_app_config("event_duration_seconds", "1800")),
                },
                on_conflict="team_id",
            ).execute()
            updated = updated + 1
        except Exception as exc:
            log.error("start_event: failed for %s: %s", tid, exc)

    _audit(None, "event_started", {"teams_activated": updated})
    return jsonify({"started": True, "team_count": updated}), 200


# ---------------------------------------------------------------------------
# POST /admin/end-event
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/end-event", methods=["POST"])
@require_admin
def end_event():
    """Set event_status=ended and auto-submit all active teams."""
    sb = _sb()
    _set_app_config("event_status", "ended")

    # Find all active teams
    teams_r = sb.table("teams").select("team_id").eq("status", "active").execute()
    active_teams = [t["team_id"] for t in (teams_r.data or [])]

    from app.services.timer_service import auto_submit

    submitted = 0
    for tid in active_teams:
        try:
            auto_submit(tid)
            submitted = submitted + 1
        except Exception as exc:
            log.error("end_event: auto_submit failed for %s: %s", tid, exc)

    _audit(None, "event_ended", {"auto_submitted": submitted})
    return jsonify({"ended": True, "auto_submitted": submitted}), 200


# ---------------------------------------------------------------------------
# POST /admin/reset-event
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/reset-event", methods=["POST"])
@require_admin
def reset_event():
    """Reset all teams, clear sessions, and set event_status=waiting."""
    sb = _sb()
    _set_app_config("event_status", "waiting")

    try:
        # Reset all teams
        sb.table("teams").update({
            "status": "waiting",
            "score": 0,
            "tab_switch_count": 0,
            "screen_locked": False,
            "login_count": 0,
            "relogin_requested": False,
            "finish_time": None
        }).neq("team_id", "xyz_never_match").execute()

        # Delete all sessions
        sb.table("sessions").delete().neq("team_id", "xyz_never_match").execute()
    except Exception as exc:
        log.error("reset_event failed: %s", exc)
        return jsonify({"error": "server_error"}), 500

    _audit(None, "event_reset", {"action": "Event completely reset by admin"})
    return jsonify({"reset": True}), 200


# ---------------------------------------------------------------------------
# POST /admin/unlock-screen
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/unlock-screen", methods=["POST"])
@require_admin
def unlock_screen():
    """Clear screen_locked for a team."""
    body    = request.get_json(silent=True) or {}
    team_id = (body.get("team_id") or "").strip().upper()
    if not team_id:
        return jsonify({"error": "bad_request", "message": "team_id required."}), 400

    try:
        _sb().table("teams").update({"screen_locked": False}).eq("team_id", team_id).execute()
    except Exception as exc:
        log.error("unlock_screen: %s %s", team_id, exc)
        return jsonify({"error": "server_error"}), 500

    _audit(team_id, "admin_screen_unlock")
    return jsonify({"unlocked": True, "team_id": team_id}), 200


# ---------------------------------------------------------------------------
# POST /admin/approve-relogin
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/approve-relogin", methods=["POST"])
@require_admin
def approve_relogin():
    """Reset login_count and relogin_requested for a team."""
    body    = request.get_json(silent=True) or {}
    team_id = (body.get("team_id") or "").strip().upper()
    if not team_id:
        return jsonify({"error": "bad_request", "message": "team_id required."}), 400

    try:
        _sb().table("teams").update(
            {"relogin_requested": False, "login_count": 0}
        ).eq("team_id", team_id).execute()
    except Exception as exc:
        log.error("approve_relogin: %s %s", team_id, exc)
        return jsonify({"error": "server_error"}), 500

    _audit(team_id, "admin_relogin_approved")
    return jsonify({"approved": True, "team_id": team_id}), 200


# ---------------------------------------------------------------------------
# POST /admin/force-submit
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/force-submit", methods=["POST"])
@require_admin
def force_submit():
    """Immediately submit a team regardless of timer."""
    body    = request.get_json(silent=True) or {}
    team_id = (body.get("team_id") or "").strip().upper()
    if not team_id:
        return jsonify({"error": "bad_request", "message": "team_id required."}), 400

    from app.services.timer_service import auto_submit
    try:
        auto_submit(team_id)
    except Exception as exc:
        log.error("force_submit: %s %s", team_id, exc)
        return jsonify({"error": "server_error"}), 500

    # Return resulting score
    try:
        r = _sb().table("teams").select("score").eq("team_id", team_id).single().execute()
        score = (r.data or {}).get("score", 0)
    except Exception:
        score = 0

    _audit(team_id, "admin_force_submit", {"score": score})
    return jsonify({"submitted": True, "score": score, "team_id": team_id}), 200


# ---------------------------------------------------------------------------
# GET /admin/leaderboard
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/leaderboard")
@require_admin
def leaderboard():
    """Top 20 submitted teams ordered by score desc, finish_time asc."""
    try:
        r = (
            _sb().table("teams")
            .select("team_id,team_name,score,finish_time")
            .eq("status", "submitted")
            .order("score", desc=True)
            .order("finish_time", desc=False)
            .limit(20)
            .execute()
        )
        rows = r.data or []
    except Exception as exc:
        log.error("leaderboard: %s", exc)
        return jsonify({"error": "server_error"}), 500

    result = [
        {
            "rank":        idx + 1,
            "team_id":     row["team_id"],
            "team_name":   row.get("team_name") or "",
            "score":       row.get("score") or 0,
            "finish_time": row.get("finish_time"),
        }
        for idx, row in enumerate(rows)
    ]
    return jsonify(result), 200


# ---------------------------------------------------------------------------
# GET /admin/audit-logs
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/audit-logs")
@require_admin
def audit_logs():
    """Last 100 audit log entries, optionally filtered by team_id."""
    team_id = request.args.get("team_id", "").strip().upper() or None

    try:
        query = (
            _sb().table("audit_logs")
            .select("team_id,event_type,timestamp,metadata")
            .order("timestamp", desc=True)
            .limit(100)
        )
        if team_id:
            query = query.eq("team_id", team_id)
        r = query.execute()
        rows = r.data or []
    except Exception as exc:
        log.error("audit_logs: %s", exc)
        return jsonify({"error": "server_error"}), 500

    return jsonify(rows), 200


# ---------------------------------------------------------------------------
# GET /admin/export-preview
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/export-preview")
@require_admin
def export_preview():
    """All submitted teams formatted for export (no Sheets call)."""
    try:
        r = (
            _sb().table("teams")
            .select("team_id,team_name,set_assigned,score,finish_time,tab_switch_count")
            .eq("status", "submitted")
            .order("score", desc=True)
            .order("finish_time", desc=False)
            .execute()
        )
        rows = r.data or []
    except Exception as exc:
        return jsonify({"error": "server_error", "message": str(exc)}), 500

    result = [
        {
            "rank":             idx + 1,
            "team_id":          row["team_id"],
            "team_name":        row.get("team_name") or "",
            "set_assigned":     row.get("set_assigned") or "",
            "score":            row.get("score") or 0,
            "finish_time":      row.get("finish_time") or "",
            "tab_switch_count": row.get("tab_switch_count") or 0,
        }
        for idx, row in enumerate(rows)
    ]
    return jsonify(result), 200


# ---------------------------------------------------------------------------
# POST /admin/export-sheets
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/export-sheets", methods=["POST"])
@require_admin
def export_sheets():
    """Write all submitted teams to Google Sheets."""
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    sheet_id   = os.getenv("GOOGLE_SHEET_ID")

    if not creds_json:
        return jsonify({"error": "misconfigured", "message": "GOOGLE_CREDS_JSON not set."}), 500
    if not sheet_id:
        return jsonify({"error": "misconfigured", "message": "GOOGLE_SHEET_ID not set."}), 500

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_dict = json.loads(creds_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet  = client.open_by_key(sheet_id).sheet1
    except Exception as exc:
        log.error("export_sheets: gspread auth failed: %s", exc)
        return jsonify({"error": "sheets_error", "message": str(exc)}), 500

    # Fetch results
    try:
        r = (
            _sb().table("teams")
            .select("team_id,team_name,set_assigned,score,finish_time,tab_switch_count")
            .eq("status", "submitted")
            .order("score", desc=True)
            .order("finish_time", desc=False)
            .execute()
        )
        teams = r.data or []
    except Exception as exc:
        return jsonify({"error": "db_error", "message": str(exc)}), 500

    # Write to sheet
    try:
        sheet.clear()
        headers: list[Any] = ["Rank", "Team ID", "Team Name", "Set", "Score", "Finish Time", "Tab Switches"]
        rows: list[list[Any]] = [headers]
        for idx, t in enumerate(teams, start=1):
            rows.append([
                idx,
                t["team_id"],
                t.get("team_name") or "",
                t.get("set_assigned") or "",
                t.get("score") or 0,
                t.get("finish_time") or "",
                t.get("tab_switch_count") or 0,
            ])
        sheet.update(rows, "A1")
    except Exception as exc:
        log.error("export_sheets: write failed: %s", exc)
        return jsonify({"error": "sheets_write_error", "message": str(exc)}), 500

    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    _audit(None, "exported_to_sheets", {"count": len(teams)})
    return jsonify({"exported": len(teams), "sheet_url": sheet_url}), 200
