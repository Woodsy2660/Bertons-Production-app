from app.config import blob_configured, resolve_storage_backend
from app.services.storage import is_remote_path, storage_key


def test_is_remote_path():
    assert is_remote_path("https://example.blob.vercel-storage.com/uploads/a.pdf")
    assert not is_remote_path("./uploads/a.pdf")


def test_storage_key_from_blob_url():
    url = "https://abc.private.blob.vercel-storage.com/uploads/file.pdf"
    assert storage_key(url) == "uploads/file.pdf"


def test_resolve_storage_backend_defaults_local(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    assert resolve_storage_backend() == "local"


def test_blob_configured_detects_token(monkeypatch):
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "token")
    assert blob_configured()