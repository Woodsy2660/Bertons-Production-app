from pathlib import Path

from app.config import blob_configured, resolve_storage_backend
from app.services.storage import is_remote_path, resolve_local_path, storage_key


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


def test_resolve_local_path_finds_upload_by_basename(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    target = upload_dir / "abc_work_order_0.pdf"
    target.write_bytes(b"%PDF-1.4 test")

    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    from app.config import get_settings

    get_settings.cache_clear()

    # Pretend DB stored a Docker absolute path
    resolved = resolve_local_path(f"/data/uploads/{target.name}")
    assert resolved == target
    # Windows-style stored path
    resolved2 = resolve_local_path(f"uploads\\{target.name}")
    assert resolved2 == target

    get_settings.cache_clear()
