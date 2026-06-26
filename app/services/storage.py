"""File storage for local disk and Vercel Blob."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import aiofiles
from pypdf import PdfReader

from app.config import get_settings


def is_remote_path(stored_path: str) -> bool:
    return stored_path.startswith("http://") or stored_path.startswith("https://")


def storage_key(stored_path: str) -> str:
    if is_remote_path(stored_path):
        return urlparse(stored_path).path.lstrip("/")
    return stored_path


async def save_bytes(
    key: str,
    content: bytes,
    *,
    content_type: str = "application/pdf",
) -> str:
    settings = get_settings()
    if settings.storage_backend == "blob":
        return await _blob_put(storage_key(key), content, content_type=content_type)

    path = Path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "wb") as handle:
        await handle.write(content)
    return str(path)


async def read_bytes(stored_path: str) -> bytes:
    if is_remote_path(stored_path):
        return await _blob_get(stored_path)
    return Path(stored_path).read_bytes()


async def delete_stored_file(stored_path: str) -> None:
    if is_remote_path(stored_path):
        await _blob_delete(stored_path)
        return
    Path(stored_path).unlink(missing_ok=True)


async def open_pdf_reader(stored_path: str) -> PdfReader:
    if is_remote_path(stored_path):
        return PdfReader(BytesIO(await read_bytes(stored_path)))
    return PdfReader(stored_path)


async def build_upload_path(batch_id, slot_value: str, sequence: int, extension: str) -> str:
    settings = get_settings()
    filename = f"{batch_id}_{slot_value}_{sequence}{extension}"
    if settings.storage_backend == "blob":
        return f"uploads/{filename}"
    return str(Path(settings.upload_dir) / filename)


async def build_compilation_path(batch_id) -> str:
    settings = get_settings()
    filename = f"compiled_{batch_id}.pdf"
    if settings.storage_backend == "blob":
        return f"compilations/{filename}"
    return str(Path(settings.upload_dir) / filename)


async def _blob_put(key: str, content: bytes, *, content_type: str) -> str:
    from vercel.blob import put_async

    settings = get_settings()
    result = await put_async(
        key,
        content,
        access=settings.blob_access,
        content_type=content_type,
        allow_overwrite=True,
    )
    return result.url


async def _blob_get(url: str) -> bytes:
    from vercel.blob import get_async

    settings = get_settings()
    result = await get_async(url, access=settings.blob_access)
    if result is None:
        raise FileNotFoundError(url)
    return result.content


async def _blob_delete(url: str) -> None:
    from vercel.blob import delete_async

    await delete_async(url)