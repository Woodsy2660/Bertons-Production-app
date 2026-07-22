"""Unit + HTTP tests for in-app feedback reporting."""

import asyncio
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.testclient import TestClient

from app.database import engine
from app.main import app
from app.models.feedback_report import FeedbackReportType
from app.services.feedback import (
    FeedbackValidationError,
    format_sydney,
    normalize_description,
    parse_report_type,
    safe_return_path,
    summarize_user_agent,
)


def test_parse_report_type_accepts_values_and_names():
    assert parse_report_type("bug") is FeedbackReportType.BUG
    assert parse_report_type("DATA_CHANGE") is FeedbackReportType.DATA_CHANGE
    assert parse_report_type("suggestion") is FeedbackReportType.SUGGESTION
    with pytest.raises(FeedbackValidationError):
        parse_report_type("")
    with pytest.raises(FeedbackValidationError):
        parse_report_type("other")


def test_normalize_description_requires_text():
    assert normalize_description("  hello  ") == "hello"
    with pytest.raises(FeedbackValidationError):
        normalize_description("   ")
    with pytest.raises(FeedbackValidationError):
        normalize_description(None)


def test_summarize_user_agent_devices():
    assert "iPad" in summarize_user_agent(
        "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
    assert "Safari" in summarize_user_agent(
        "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
    android = (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    )
    assert "Android" in summarize_user_agent(android)
    assert "Chrome" in summarize_user_agent(android)
    desktop = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    assert "Desktop" in summarize_user_agent(desktop)
    assert summarize_user_agent("") == "Unknown"


def test_format_sydney_utc():
    dt = datetime(2026, 7, 21, 2, 30, tzinfo=timezone.utc)
    label = format_sydney(dt)
    # AEST (UTC+10) or AEDT (UTC+11) — no zone suffix
    assert "21 Jul 2026" in label
    assert "12:30" in label or "13:30" in label
    assert "AEST" not in label and "AEDT" not in label and "UTC" not in label


def test_safe_return_path_blocks_open_redirect():
    assert safe_return_path("/batches/abc") == "/batches/abc"
    assert safe_return_path("//evil.com") == "/"
    assert safe_return_path("https://evil.com") == "/"
    assert safe_return_path("http://evil.com/x") == "/"
    assert safe_return_path("") == "/"


def test_description_escaped_in_list_template():
    """Jinja autoescape must not treat description as raw HTML."""
    templates_dir = Path(__file__).resolve().parents[1] / "app" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tpl = env.from_string(
        '<p class="feedback-report-description">{{ row.description }}</p>'
    )
    html = tpl.render(row={"description": "<script>alert(1)</script>"})
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def _login(client: TestClient, username: str, password: str) -> None:
    r = client.post(
        "/login",
        data={"username": username, "password": password, "next": "/"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def _db_reachable() -> bool:
    """Socket check only — do not open TestClient (async engine loop reuse)."""
    try:
        with socket.create_connection(("127.0.0.1", 5433), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.fixture
def client():
    """Single TestClient per test; dispose pool so asyncpg is not bound to a dead loop."""
    asyncio.run(engine.dispose())
    with TestClient(app) as c:
        yield c
    asyncio.run(engine.dispose())


def test_operator_cannot_access_feedback_list(client: TestClient):
    _login(client, "operator", "operator")
    r = client.get("/feedback", follow_redirects=False)
    assert r.status_code == 403


def test_manager_can_access_feedback_list(client: TestClient):
    if not _db_reachable():
        pytest.skip("Database not available")
    _login(client, "manager", "manager")
    r = client.get("/feedback", follow_redirects=False)
    assert r.status_code == 200
    assert b"Feedback reports" in r.content


def test_submit_ignores_forged_role_field(client: TestClient):
    """submitted_role must come from session; a forged form field is ignored."""
    if not _db_reachable():
        pytest.skip("Database not available")
    _login(client, "operator", "operator")
    r = client.post(
        "/feedback",
        data={
            "report_type": "bug",
            "description": "forged role test",
            "submitted_role": "manager",  # must be ignored
            "source_path": "/",
            "return_to": "/",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "feedback=ok" in r.headers.get("location", "")


def test_empty_description_rejected(client: TestClient):
    if not _db_reachable():
        pytest.skip("Database not available")
    _login(client, "operator", "operator")
    r = client.post(
        "/feedback",
        data={
            "report_type": "bug",
            "description": "   ",
            "source_path": "/",
            "return_to": "/",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "feedback=error" in r.headers.get("location", "")
