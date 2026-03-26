"""conftest.py — pytest fixtures for the Math Quiz platform.

Uses unittest.mock to patch the Supabase client so tests run
without any real database credentials.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from app.config import TestingConfig


# ---------------------------------------------------------------------------
# Supabase mock factory
# ---------------------------------------------------------------------------

def _make_supabase_mock():
    """Return a MagicMock that satisfies all Supabase chained-call patterns.

    Any .table(x).select(y).eq(z).single().execute() chain returns a
    mock result with result.data = None by default, and can be overridden
    per test.
    """
    mock = MagicMock()

    # Make every chained call return the same mock (fluent interface)
    mock.table.return_value = mock
    mock.select.return_value = mock
    mock.insert.return_value = mock
    mock.update.return_value = mock
    mock.upsert.return_value = mock
    mock.delete.return_value = mock
    mock.eq.return_value = mock
    mock.neq.return_value = mock
    mock.order.return_value = mock
    mock.limit.return_value = mock
    mock.single.return_value = mock

    # Default execute() returns empty data
    execute_result = MagicMock()
    execute_result.data = None
    mock.execute.return_value = execute_result

    return mock


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def supabase_mock():
    """Session-scoped Supabase mock — shared across all tests."""
    return _make_supabase_mock()


@pytest.fixture(scope="session")
def app(supabase_mock):
    """Create Flask test application with mocked Supabase."""
    with patch("app.models.db.get_supabase", return_value=supabase_mock):
        flask_app = create_app(TestingConfig)
        flask_app.config["TESTING"] = True
        yield flask_app


@pytest.fixture(scope="session")
def client(app):
    """Flask test client."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Auth helper — generates a real test JWT for protected route tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_jwt(app):
    """A valid JWT for team TEAM001 / set A — signed with TestingConfig secret."""
    from app.services.auth_service import create_token
    with app.app_context():
        return create_token("TEAM001", "A", duration_seconds=3600)


@pytest.fixture(scope="session")
def auth_headers(test_jwt):
    return {
        "Authorization": f"Bearer {test_jwt}",
        "Content-Type": "application/json",
    }
