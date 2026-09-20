"""
Writing uploads to disk.

Both upload endpoints go through here so there is one answer to "what happens
when someone posts a huge file": it never lands in memory whole, and it stops
being written the moment it crosses the limit rather than after.
"""
from __future__ import annotations

from pathlib import Path

import anyio
from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import FileTooLargeError

_CHUNK_BYTES = 64 * 1024


async def save_upload(file: UploadFile, dest: Path) -> int:
    """
    Stream `file` into `dest` and return the byte count.

    Raises FileTooLargeError once more than the configured limit has arrived,
    deleting the partial file first so a rejected upload leaves nothing behind.
    Trusting Content-Length instead would mean trusting the client about the
    size of the body it is still sending.
    """
    size = 0
    try:
        async with await anyio.open_file(dest, "wb") as out:
            while chunk := await file.read(_CHUNK_BYTES):
                size += len(chunk)
                if size > settings.max_upload_size_bytes:
                    raise FileTooLargeError(
                        f"File exceeds the {settings.max_upload_size_mb}MB upload limit."
                    )
                await out.write(chunk)
    except BaseException:
        await anyio.Path(dest).unlink(missing_ok=True)
        raise

    return size
