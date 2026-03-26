"""Quiz routes blueprint.

Endpoints:
  GET  /quiz              — serve quiz.html (protected)
  GET  /api/questions     — fetch questions + session state
  POST /save-progress     — upsert answers to sessions table
  POST /submit            — finalize submission + calculate score
"""
import logging
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, render_template, request

from app.models.db import get_supabase
from app.services.auth_service import require_auth
from app.services.question_service import calculate_score, get_questions_for_team

log = logging.getLogger(__name__)

quiz_bp = Blueprint("quiz", __name__)

_DEFAULT_DURATION = 1800


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_event_duration() -> int:
    try:
        r = (
            get_supabase()
            .table("app_config")
            .select("value")
            .eq("key", "event_duration_seconds")
            .single()
            .execute()
        )
        return int(r.data["value"])
    except Exception:
        return _DEFAULT_DURATION


def _remaining_seconds(server_start_str: str, event_duration: int) -> int:
    """Calculate seconds remaining from server_start_time string."""
    try:
        server_start = datetime.fromisoformat(server_start_str.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - server_start).total_seconds()
        return max(0, int(event_duration - elapsed))
    except Exception:
        return 0


def _log_audit(team_id: str, event_type: str, metadata: dict | None = None) -> None:
    try:
        get_supabase().table("audit_logs").insert(
            {"team_id": team_id, "event_type": event_type, "metadata": metadata or {}}
        ).execute()
    except Exception as exc:
        log.warning("audit_log failed (%s %s): %s", team_id, event_type, exc)


# ---------------------------------------------------------------------------
# GET /quiz — serve the HTML shell
# ---------------------------------------------------------------------------

@quiz_bp.route("/quiz")
def quiz_page():
    return render_template("quiz.html")



# ---------------------------------------------------------------------------
# GET /api/questions
# ---------------------------------------------------------------------------

@quiz_bp.route("/api/questions")
@require_auth
def api_questions():
    team_id      = g.team_id
    set_assigned = g.set_assigned
    sb           = get_supabase()

    # ── Check team status ─────────────────────────────────────────────
    try:
        team_r = (
            sb.table("teams")
            .select("status,score,finish_time")
            .eq("team_id", team_id)
            .single()
            .execute()
        )
        team = team_r.data or {}
    except Exception as exc:
        log.error("api_questions: team fetch failed for %s: %s", team_id, exc)
        return jsonify({"error": "server_error", "message": "Could not fetch team data."}), 500

    if team.get("status") == "submitted":
        return jsonify(
            {
                "status":      "submitted",
                "score":       team.get("score", 0),
                "finish_time": team.get("finish_time"),
            }
        ), 200

    # ── Fetch session ─────────────────────────────────────────────────
    try:
        sess_r = (
            sb.table("sessions")
            .select("answers_json,server_start_time")
            .eq("team_id", team_id)
            .single()
            .execute()
        )
        session = sess_r.data or {}
    except Exception as exc:
        log.error("api_questions: session fetch failed for %s: %s", team_id, exc)
        return jsonify({"error": "server_error", "message": "Could not fetch session."}), 500

    event_duration   = _get_event_duration()
    saved_answers    = session.get("answers_json") or {}
    rem_secs         = _remaining_seconds(
        session.get("server_start_time", ""), event_duration
    )

    # ── Get questions (strip internal field) ──────────────────────────
    try:
        raw_questions = get_questions_for_team(team_id, set_assigned)
    except RuntimeError as exc:
        log.error("api_questions: %s", exc)
        return jsonify({"error": "no_questions", "message": str(exc)}), 500

    questions = [
        {k: v for k, v in q.items() if not k.startswith("_")}
        for q in raw_questions
    ]

    return jsonify(
        {
            "questions":         questions,
            "remaining_seconds": rem_secs,
            "saved_answers":     saved_answers,
            "total":             len(questions),
        }
    ), 200


# ---------------------------------------------------------------------------
# POST /save-progress
# ---------------------------------------------------------------------------

@quiz_bp.route("/save-progress", methods=["POST"])
@require_auth
def save_progress():
    team_id = g.team_id
    body    = request.get_json(silent=True) or {}
    answers = body.get("answers", {})

    if not isinstance(answers, dict):
        return jsonify({"error": "bad_request", "message": "answers must be an object."}), 400

    try:
        get_supabase().table("sessions").update(
            {
                "answers_json":  answers,
                "last_saved_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("team_id", team_id).execute()
    except Exception as exc:
        log.error("save_progress: failed for %s: %s", team_id, exc)
        return jsonify({"error": "server_error", "message": "Could not save progress."}), 500

    return jsonify({"saved": True}), 200


# ---------------------------------------------------------------------------
# POST /submit
# ---------------------------------------------------------------------------

@quiz_bp.route("/submit", methods=["POST"])
@require_auth
def submit():
    team_id      = g.team_id
    set_assigned = g.set_assigned
    sb           = get_supabase()

    # ── Idempotency: check if already submitted ───────────────────────
    try:
        team_r = (
            sb.table("teams")
            .select("status,score,finish_time")
            .eq("team_id", team_id)
            .single()
            .execute()
        )
        team = team_r.data or {}
    except Exception as exc:
        log.error("submit: team fetch failed for %s: %s", team_id, exc)
        return jsonify({"error": "server_error", "message": "Could not fetch team."}), 500

    if team.get("status") == "submitted":
        return jsonify(
            {
                "score":       team.get("score", 0),
                "total":       30,
                "finish_time": team.get("finish_time"),
                "already_submitted": True,
            }
        ), 200

    # ── Fetch saved answers from sessions (ignore request body for security) ──
    try:
        sess_r = (
            sb.table("sessions")
            .select("answers_json")
            .eq("team_id", team_id)
            .single()
            .execute()
        )
        answers = sess_r.data.get("answers_json") or {} if sess_r.data else {}
    except Exception as exc:
        log.error("submit: session fetch failed for %s: %s", team_id, exc)
        answers = {}

    # ── Score ─────────────────────────────────────────────────────────
    try:
        score = calculate_score(team_id, set_assigned, answers)
    except Exception as exc:
        log.error("submit: score calc failed for %s: %s", team_id, exc)
        score = 0

    now_utc = datetime.now(timezone.utc).isoformat()

    # ── Persist ───────────────────────────────────────────────────────
    try:
        sb.table("teams").update(
            {
                "status":      "submitted",
                "score":       score,
                "finish_time": now_utc,
            }
        ).eq("team_id", team_id).execute()
    except Exception as exc:
        log.error("submit: teams update failed for %s: %s", team_id, exc)
        return jsonify({"error": "server_error", "message": "Could not record submission."}), 500

    _log_audit(team_id, "submitted", {"score": score, "source": "manual"})

    return jsonify(
        {
            "score":       score,
            "total":       30,
            "finish_time": now_utc,
        }
    ), 200
