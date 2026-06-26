from app.auth.credentials import verify_credentials
from app.config import Settings


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