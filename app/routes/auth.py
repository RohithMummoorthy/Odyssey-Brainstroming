"""Auth routes blueprint.

Endpoints:
  POST /login          — validate PIN, issue JWT, restore/create session
  POST /logout         — protected; client clears localStorage
  GET  /session-status — protected; return remaining time + saved answers
"""
import logging
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, g

from app.models.db import get_supabase
from app.services.auth_service import (
    verify_pin,
    create_token,
    require_auth,
)

log = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

# Default quiz duration (seconds). Overridden by app_config at runtime.
_DEFAULT_DURATION = 1800


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_event_duration() -> int:
    """Fetch event_duration_seconds from app_config, falling back to default."""
    try:
        sb = get_supabase()
        result = (
            sb.table("app_config")
            .select("value")
            .eq("key", "event_duration_seconds")
            .single()
            .execute()
        )
        return int(result.data["value"])
    except Exception:
        return _DEFAULT_DURATION


def _log_audit(team_id: str, event_type: str, metadata: dict | None = None) -> None:
    """Insert a row into audit_logs (best-effort; never raises)."""
    try:
        get_supabase().table("audit_logs").insert(
            {
                "team_id":    team_id,
                "event_type": event_type,
                "metadata":   metadata or {},
            }
        ).execute()
    except Exception as exc:
        log.warning("audit_log insert failed (%s %s): %s", team_id, event_type, exc)


def _auto_submit(team_id: str) -> None:
    """Submit a team when their time runs out (best-effort, with scoring)."""
    try:
        from app.services.timer_service import auto_submit as timed_auto_submit
        timed_auto_submit(team_id)
    except Exception as exc:
        log.warning("auto_submit failed for %s: %s", team_id, exc)


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------

@auth_bp.route("/login", methods=["POST"])
def login():
    """Authenticate a team and return a JWT + session state."""
    body = request.get_json(silent=True) or {}
    team_id = (body.get("team_id") or "").strip().upper()
    pin     = (body.get("pin")     or "").strip()

    if not team_id or not pin:
        return jsonify({"error": "bad_request", "message": "team_id and pin are required."}), 400

    sb = get_supabase()

    # ── Fetch team ──────────────────────────────────────────────────────
    try:
        team_result = (
            sb.table("teams")
            .select("team_id,pin_hash,set_assigned,status,login_count,relogin_requested")
            .eq("team_id", team_id)
            .single()
            .execute()
        )
    except Exception:
        # .single() raises if 0 rows returned
        return jsonify({"error": "invalid_credentials", "message": "Team ID or PIN is incorrect."}), 401

    team = team_result.data
    if not team:
        return jsonify({"error": "invalid_credentials", "message": "Team ID or PIN is incorrect."}), 401

    # ── Verify PIN ──────────────────────────────────────────────────────
    if not verify_pin(pin, team["pin_hash"]):
        _log_audit(team_id, "login_failed_wrong_pin")
        return jsonify({"error": "invalid_credentials", "message": "Team ID or PIN is incorrect."}), 401

    team_status = team.get("status") or "waiting"

    # ── Team state checks ────────────────────────────────────────────────
    if team_status == "submitted":
        return jsonify({"error": "already_submitted", "message": "Your team has already submitted."}), 403
    if team_status == "waiting":
        return jsonify({"error": "event_not_started", "message": "Quiz has not started yet."}), 403
    if team_status != "active":
        return jsonify({"error": "event_unavailable", "message": "Quiz is not available right now."}), 403

    # ── Re-login check ──────────────────────────────────────────────────
    login_count: int = team.get("login_count") or 0
    if login_count > 0 and team_status == "active":
        # Phase 5 will add explicit admin approval gate.
        # For now: allow but log.
        log.info("Re-login: %s (relogin_requested=%s)", team_id, team.get("relogin_requested"))
        _log_audit(team_id, "relogin", {"relogin_requested": team.get("relogin_requested")})

    # ── Increment login_count ───────────────────────────────────────────
    try:
        sb.table("teams").update({"login_count": login_count + 1}).eq("team_id", team_id).execute()
    except Exception as exc:
        log.error("Failed to update login_count for %s: %s", team_id, exc)
        return jsonify({"error": "server_error", "message": "Please try again."}), 500

    # ── Restore or create session ────────────────────────────────────────
    event_duration = _get_event_duration()
    now_utc = datetime.now(timezone.utc)

    try:
        session_result = (
            sb.table("sessions")
            .select("*")
            .eq("team_id", team_id)
            .execute()
        )
        session_rows = session_result.data or []
    except Exception as exc:
        log.error("Session fetch failed for %s: %s", team_id, exc)
        session_rows = []

    if session_rows:
        # ── Restore existing session ─────────────────────────────────────
        session = session_rows[0]
        saved_answers = session.get("answers_json") or {}

        # Calculate remaining time
        server_start_str = session.get("server_start_time")
        if server_start_str:
            try:
                server_start = datetime.fromisoformat(
                    server_start_str.replace("Z", "+00:00")
                )
                elapsed = int((now_utc - server_start).total_seconds())
                remaining_seconds = max(0, event_duration - elapsed)
            except Exception:
                remaining_seconds = session.get("remaining_seconds", event_duration)
        else:
            remaining_seconds = session.get("remaining_seconds", event_duration)

        _log_audit(team_id, "login_restored_session", {"remaining_seconds": remaining_seconds})

    else:
        # ── Create new session ───────────────────────────────────────────
        saved_answers    = {}
        remaining_seconds = event_duration

        try:
            sb.table("sessions").insert(
                {
                    "team_id":           team_id,
                    "answers_json":      {},
                    "server_start_time": now_utc.isoformat(),
                    "remaining_seconds": remaining_seconds,
                }
            ).execute()
        except Exception as exc:
            log.error("Session create failed for %s: %s", team_id, exc)
            return jsonify({"error": "server_error", "message": "Could not create session."}), 500

        _log_audit(team_id, "login_new_session")

    # ── Issue JWT ────────────────────────────────────────────────────────
    set_assigned = team.get("set_assigned") or "A"
    token = create_token(team_id, set_assigned, duration_seconds=event_duration)

    return jsonify(
        {
            "token":            token,
            "team_id":          team_id,
            "set_assigned":     set_assigned,
            "remaining_seconds": remaining_seconds,
            "saved_answers":    saved_answers,
        }
    ), 200


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------

@auth_bp.route("/logout", methods=["POST"])
@require_auth
def logout():
    """Invalidate client side — client must clear localStorage."""
    _log_audit(g.team_id, "logout")
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# GET /session-status
# ---------------------------------------------------------------------------

@auth_bp.route("/session-status", methods=["GET"])
@require_auth
def session_status():
    """Return current remaining_seconds and saved answers for the team.

    If time has run out, auto-submits and returns status='submitted'.
    """
    team_id = g.team_id
    sb = get_supabase()

    # -- Fetch session ------------------------------------------------------
    try:
        result = (
            sb.table("sessions")
            .select("*")
            .eq("team_id", team_id)
            .single()
            .execute()
        )
        session = result.data
    except Exception as exc:
        log.error("session-status fetch failed for %s: %s", team_id, exc)
        return jsonify({"error": "server_error", "message": "Could not fetch session."}), 500

    if not session:
        return jsonify({"error": "no_session", "message": "No active session found."}), 404

    # -- Calculate remaining seconds ----------------------------------------
    try:
        event_duration = _get_event_duration()
        server_start = datetime.fromisoformat(
            session["server_start_time"].replace("Z", "+00:00")
        )
        elapsed = int((datetime.now(timezone.utc) - server_start).total_seconds())
        remaining_seconds = max(0, event_duration - elapsed)
    except Exception:
        remaining_seconds = max(0, session.get("remaining_seconds", 0))

    # -- Auto-submit if expired ---------------------------------------------
    if remaining_seconds <= 0:
        _auto_submit(team_id)
        return jsonify({"status": "submitted", "remaining_seconds": 0}), 200

    return jsonify(
        {
            "remaining_seconds": remaining_seconds,
            "saved_answers":     session.get("answers_json") or {},
        }
    ), 200
