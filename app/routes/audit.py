"""Audit routes blueprint.

Endpoints:
  POST /audit/log        — insert audit event; side-effects for tab_switch / fullscreen_exit
  GET  /api/lock-status  — return screen_locked flag for the calling team
"""
import logging

from flask import Blueprint, g, jsonify, request

from app.models.db import get_supabase
from app.services.auth_service import require_auth

log = logging.getLogger(__name__)

audit_bp = Blueprint("audit", __name__)


# ---------------------------------------------------------------------------
# POST /audit/log
# ---------------------------------------------------------------------------

@audit_bp.route("/audit/log", methods=["POST"])
@require_auth
def audit_log():
    """Insert an audit log row and apply any side-effects."""
    team_id    = g.team_id
    body       = request.get_json(silent=True) or {}
    event_type = (body.get("event_type") or "").strip()
    metadata   = body.get("metadata") or {}

    if not event_type:
        return jsonify({"error": "bad_request", "message": "event_type is required."}), 400

    sb = get_supabase()

    # ── Insert audit row ──────────────────────────────────────────────
    try:
        sb.table("audit_logs").insert(
            {
                "team_id":    team_id,
                "event_type": event_type,
                "metadata":   metadata,
            }
        ).execute()
    except Exception as exc:
        log.error("audit_log insert failed (%s %s): %s", team_id, event_type, exc)
        return jsonify({"error": "server_error", "message": "Could not log event."}), 500

    # ── Side-effects ──────────────────────────────────────────────────
    if event_type == "tab_switch":
        _increment_tab_switch(sb, team_id)

    elif event_type == "fullscreen_exit":
        _set_screen_locked(sb, team_id, locked=True)

    return jsonify({"logged": True}), 200


# ---------------------------------------------------------------------------
# GET /api/lock-status
# ---------------------------------------------------------------------------

@audit_bp.route("/api/lock-status", methods=["GET"])
@require_auth
def lock_status():
    """Return whether the admin has locked this team's screen."""
    team_id = g.team_id
    sb      = get_supabase()

    try:
        result = (
            sb.table("teams")
            .select("screen_locked")
            .eq("team_id", team_id)
            .single()
            .execute()
        )
        locked = bool(result.data.get("screen_locked", False)) if result.data else False
    except Exception as exc:
        log.error("lock_status fetch failed for %s: %s", team_id, exc)
        # Fail safe — treat as locked so the team contacts admin
        return jsonify({"locked": True}), 200

    return jsonify({"locked": locked}), 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _increment_tab_switch(sb, team_id: str) -> None:
    """Increment tab_switch_count on the teams row (best-effort)."""
    try:
        # Supabase Python client doesn't support column += directly;
        # use a raw RPC increment or fetch-then-update pattern.
        current_r = (
            sb.table("teams")
            .select("tab_switch_count")
            .eq("team_id", team_id)
            .single()
            .execute()
        )
        current_count = (current_r.data or {}).get("tab_switch_count") or 0
        sb.table("teams").update(
            {"tab_switch_count": current_count + 1}
        ).eq("team_id", team_id).execute()
    except Exception as exc:
        log.warning("tab_switch_count increment failed for %s: %s", team_id, exc)


def _set_screen_locked(sb, team_id: str, locked: bool) -> None:
    """Set screen_locked flag on the teams row (best-effort)."""
    try:
        sb.table("teams").update(
            {"screen_locked": locked}
        ).eq("team_id", team_id).execute()
    except Exception as exc:
        log.warning("screen_locked update failed for %s: %s", team_id, exc)
