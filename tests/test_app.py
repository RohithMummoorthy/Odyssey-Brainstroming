"""test_app.py — Smoke tests for Math Quiz platform.

All Supabase calls are mocked via conftest.py fixtures.
Tests verify routing, auth guards, and response shapes —
not business logic (which requires real DB).

Run: pytest tests/ -v
"""
import json
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health_check(client):
    """GET /health must return 200 with status=ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["message"] == "hi"
    assert data["status"] == "ok"
    assert "timestamp" in data


# ---------------------------------------------------------------------------
# Auth — /login
# ---------------------------------------------------------------------------

def test_login_missing_fields_returns_400(client):
    """POST /login with empty body → 400."""
    resp = client.post(
        "/login",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "bad_request"


def test_login_wrong_pin_returns_401(client, supabase_mock):
    """POST /login with non-existent team → 401."""
    # Make supabase raise an exception (team not found — .single() raises)
    supabase_mock.execute.side_effect = Exception("PGRST116 - no rows")
    try:
        resp = client.post(
            "/login",
            data=json.dumps({"team_id": "FAKE999", "pin": "0000"}),
            content_type="application/json",
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["error"] in ("invalid_credentials", "server_error")
    finally:
        # Restore default mock behaviour for other tests
        supabase_mock.execute.side_effect = None
        result = MagicMock()
        result.data = None
        supabase_mock.execute.return_value = result


# ---------------------------------------------------------------------------
# Quiz — /api/questions
# ---------------------------------------------------------------------------

def test_quiz_no_auth_returns_401(client):
    """GET /api/questions without a token → 401."""
    resp = client.get("/api/questions")
    assert resp.status_code == 401


def test_quiz_bad_token_returns_401(client):
    """GET /api/questions with a mangled token → 401."""
    resp = client.get(
        "/api/questions",
        headers={"Authorization": "Bearer this.is.garbage"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Admin — /admin/login
# ---------------------------------------------------------------------------

def test_admin_wrong_password_returns_401(client):
    """POST /admin/login with wrong password → 401."""
    resp = client.post(
        "/admin/login",
        data=json.dumps({"password": "totally-wrong"}),
        content_type="application/json",
    )
    assert resp.status_code == 401
    data = resp.get_json()
    assert data["error"] == "unauthorized"


def test_admin_no_token_returns_401(client):
    """GET /admin/status without admin token → 401."""
    resp = client.get("/admin/status")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Audit — /audit/log
# ---------------------------------------------------------------------------

def test_audit_no_auth_returns_401(client):
    """POST /audit/log without a token → 401."""
    resp = client.post(
        "/audit/log",
        data=json.dumps({"event_type": "test"}),
        content_type="application/json",
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Leaderboard — public
# ---------------------------------------------------------------------------

def test_leaderboard_page_is_public(client, supabase_mock):
    """GET /leaderboard must return 200 — no auth required."""
    # Setup mock to return empty lists for all table queries
    execute_result = MagicMock()
    execute_result.data = []
    supabase_mock.execute.return_value = execute_result

    resp = client.get("/leaderboard")
    assert resp.status_code == 200


def test_leaderboard_api_is_public(client, supabase_mock):
    """GET /api/leaderboard returns 200 JSON — no auth required."""
    execute_result = MagicMock()
    execute_result.data = []
    supabase_mock.execute.return_value = execute_result

    resp = client.get("/api/leaderboard")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "leaders" in data


# ---------------------------------------------------------------------------
# HTML pages — serve templates
# ---------------------------------------------------------------------------

def test_login_page_returns_200(client):
    """GET / serves login page."""
    resp = client.get("/")
    assert resp.status_code == 200


def test_admin_panel_page_returns_200(client):
    """GET /admin-panel serves admin HTML."""
    resp = client.get("/admin-panel")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Save-progress — protected
# ---------------------------------------------------------------------------

def test_save_progress_no_auth(client):
    """POST /save-progress without token → 401."""
    resp = client.post(
        "/save-progress",
        data=json.dumps({"answers": {}}),
        content_type="application/json",
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Submit — protected
# ---------------------------------------------------------------------------

def test_submit_no_auth(client):
    """POST /submit without token → 401."""
    resp = client.post("/submit")
    assert resp.status_code == 401
