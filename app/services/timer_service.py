"""Timer service — background scheduler that auto-submits expired sessions.

Uses APScheduler's BackgroundScheduler so it runs in-process without a Celery
worker. The scheduler checks every 10 seconds for sessions whose elapsed time
exceeds the configured event_duration_seconds.

Usage (called from app factory):
    from app.services.timer_service import init_scheduler
    init_scheduler(app)
"""
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_EVENT_DURATION_DEFAULT = 1800   # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_supabase():
    """Lazy import to avoid circular imports at module load time."""
    from app.models.db import get_supabase
    return get_supabase()


def _get_event_duration() -> int:
    """Read event_duration_seconds from app_config."""
    try:
        result = (
            _get_supabase()
            .table("app_config")
            .select("value")
            .eq("key", "event_duration_seconds")
            .single()
            .execute()
        )
        return int(result.data["value"])
    except Exception:
        return _EVENT_DURATION_DEFAULT


def auto_submit(team_id: str, answers_json: dict | None = None) -> None:
    """Score and mark a team as submitted.

    Args:
        team_id: The team to submit.
        answers_json: Pre-fetched answers dict, or None to fetch from DB.
    """
    sb = _get_supabase()

    # ── Fetch answers if not provided ─────────────────────────────────
    if answers_json is None:
        try:
            result = (
                sb.table("sessions")
                .select("answers_json")
                .eq("team_id", team_id)
                .single()
                .execute()
            )
            answers_json = result.data.get("answers_json") or {} if result.data else {}
        except Exception as exc:
            log.error("auto_submit: failed to fetch session for %s: %s", team_id, exc)
            answers_json = {}

    # ── Fetch team's set_assigned ─────────────────────────────────────
    try:
        team_result = (
            sb.table("teams")
            .select("set_assigned,status")
            .eq("team_id", team_id)
            .single()
            .execute()
        )
        team = team_result.data or {}
    except Exception as exc:
        log.error("auto_submit: failed to fetch team %s: %s", team_id, exc)
        return

    if team.get("status") == "submitted":
        return   # already done, idempotent

    set_assigned = team.get("set_assigned") or "A"

    # ── Calculate score ───────────────────────────────────────────────
    from app.services.question_service import calculate_score
    try:
        score = calculate_score(team_id, set_assigned, answers_json)
    except Exception as exc:
        log.error("auto_submit: score calculation failed for %s: %s", team_id, exc)
        score = 0

    # ── Update teams table ────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("teams").update(
            {
                "status":      "submitted",
                "score":       score,
                "finish_time": now_utc,
            }
        ).eq("team_id", team_id).execute()
        log.info("auto_submit: %s submitted, score=%d", team_id, score)
    except Exception as exc:
        log.error("auto_submit: failed to update team %s: %s", team_id, exc)

    # ── Audit log ─────────────────────────────────────────────────────
    try:
        sb.table("audit_logs").insert(
            {
                "team_id":    team_id,
                "event_type": "auto_submitted",
                "metadata":   {"score": score, "source": "timer_service"},
            }
        ).execute()
    except Exception as exc:
        log.warning("auto_submit: audit log failed for %s: %s", team_id, exc)


# ---------------------------------------------------------------------------
# Scheduled job
# ---------------------------------------------------------------------------

def check_expired_sessions() -> None:
    """Find and auto-submit all sessions that have exceeded event duration.

    Runs every 10 seconds via APScheduler.
    """
    try:
        sb = _get_supabase()
        event_duration = _get_event_duration()

        # Fetch all active sessions with their start times
        result = (
            sb.table("sessions")
            .select("team_id,server_start_time,answers_json")
            .execute()
        )
        sessions = result.data or []
    except Exception as exc:
        log.error("check_expired_sessions: DB error: %s", exc)
        return

    now_utc = datetime.now(timezone.utc)
    expired_count = 0

    for session in sessions:
        team_id    = session.get("team_id")
        start_str  = session.get("server_start_time")
        answers    = session.get("answers_json") or {}

        if not team_id or not start_str:
            continue

        try:
            server_start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            elapsed = (now_utc - server_start).total_seconds()
            if elapsed >= event_duration:
                auto_submit(team_id, answers)
                expired_count += 1
        except Exception as exc:
            log.error("check_expired_sessions: error processing %s: %s", team_id, exc)

    if expired_count:
        log.info("check_expired_sessions: auto-submitted %d team(s)", expired_count)


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def init_scheduler(app) -> None:
    """Start the APScheduler background scheduler.

    Safe to call multiple times (idempotent — won't start a second scheduler).
    Should be called from the Flask app factory.
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        return   # Already started (e.g., Gunicorn worker reload)

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        func=check_expired_sessions,
        trigger=IntervalTrigger(seconds=10),
        id="check_expired_sessions",
        name="Auto-submit expired quiz sessions",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    log.info("Timer scheduler started (check interval: 10 s)")

    # Shut down cleanly when the Flask dev server exits
    import atexit
    atexit.register(lambda: _scheduler.shutdown(wait=False))
