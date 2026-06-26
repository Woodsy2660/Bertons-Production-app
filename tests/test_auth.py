from starlette.testclient import TestClient

from app.auth.credentials import verify_credentials
from app.config import Settings
from app.main import app


def test_manager_credentials():
    settings = Settings(
        manager_username="mgr",
        manager_password="secret",
        operator_username="op",
        operator_password="pass",
    )
    assert verify_credentials("mgr", "secret", settings) == "manager"
    assert verify_credentials("op", "pass", settings) == "operator"
    assert verify_credentials("mgr", "wrong", settings) is None
    assert verify_credentials("", "", settings) is None


def test_login_sets_session_and_reaches_dashboard():
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"username": "manager", "password": "manager", "next": "/"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        assert login.headers["location"] == "/"
        assert "session" in login.cookies

        home = client.get("/", follow_redirects=False)
        assert home.status_code == 200