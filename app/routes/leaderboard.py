"""leaderboard.py — Public projector leaderboard route (no auth required).

GET /leaderboard → renders leaderboard.html with live data
GET /api/leaderboard → returns JSON for the HTML auto-refresh
"""
import logging

from flask import Blueprint, jsonify, render_template

from app.models.db import get_supabase

log = logging.getLogger(__name__)

leaderboard_bp = Blueprint("leaderboard", __name__)


def _get_leaderboard_data() -> dict:
    """Fetch leaderboard data from Supabase."""
    sb = get_supabase()

    # Top 10 submitted teams
    try:
        top10_r = (
            sb.table("teams")
            .select("team_id,team_name,score,finish_time,set_assigned")
            .eq("status", "submitted")
            .order("score", desc=True)
            .order("finish_time", desc=False)
            .limit(10)
            .execute()
        )
        top10 = top10_r.data or []
    except Exception as exc:
        log.error("leaderboard: top10 fetch failed: %s", exc)
        top10 = []

    # Count stats
    try:
        all_r = (
            sb.table("teams")
            .select("status")
            .execute()
        )
        all_teams     = all_r.data or []
        total         = len(all_teams)
        submitted     = sum(1 for t in all_teams if t["status"] == "submitted")
        active        = sum(1 for t in all_teams if t["status"] == "active")
    except Exception as exc:
        log.error("leaderboard: stats fetch failed: %s", exc)
        total = submitted = active = 0

    # Event status
    try:
        ev_r = (
            sb.table("app_config")
            .select("value")
            .eq("key", "event_status")
            .single()
            .execute()
        )
        event_status = (ev_r.data or {}).get("value", "waiting")
    except Exception:
        event_status = "waiting"

    # Enrich top10 with time_taken
    from app.models.db import get_supabase as _gsb
    try:
        sess_r = _gsb().table("sessions").select("team_id,server_start_time").execute()
        start_times = {s["team_id"]: s.get("server_start_time") for s in (sess_r.data or [])}
    except Exception:
        start_times = {}

    from datetime import datetime
    leaders = []
    for idx, t in enumerate(top10, start=1):
        tid         = t["team_id"]
        finish_time = t.get("finish_time")
        start_str   = start_times.get(tid)
        time_taken  = None
        if finish_time and start_str:
            try:
                ft = datetime.fromisoformat(finish_time.replace("Z", "+00:00"))
                st = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                time_taken = round((ft - st).total_seconds() / 60, 1)
            except Exception:
                pass

        leaders.append({
            "rank":        idx,
            "team_id":     tid,
            "team_name":   t.get("team_name") or tid,
            "score":       t.get("score") or 0,
            "time_taken":  time_taken,
            "set_assigned": t.get("set_assigned") or "",
        })

    return {
        "leaders":      leaders,
        "total":        total,
        "submitted":    submitted,
        "active":       active,
        "event_status": event_status,
    }


# ── Routes ─────────────────────────────────────────────────────────────────

@leaderboard_bp.route("/leaderboard")
def leaderboard_page():
    """Public projector leaderboard (no auth required)."""
    data = _get_leaderboard_data()
    return render_template("leaderboard.html", **data)


@leaderboard_bp.route("/api/leaderboard")
def leaderboard_api():
    """JSON endpoint for leaderboard auto-refresh."""
    return jsonify(_get_leaderboard_data()), 200
