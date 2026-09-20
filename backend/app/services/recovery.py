"""
Startup recovery for ingestion that died with the process.

Ingestion runs as a FastAPI BackgroundTask, so it lives and dies with the
server. An exception inside `ingest_document` marks the document failed, but a
crash, a restart or a deploy kills the task with no chance to do that, leaving
the row on `processing` forever and the UI spinning on a document that will
never finish.

Nothing can be mid-ingest during startup, so anything still marked `processing`
when we boot is a casualty of the previous process: mark it failed with a reason
the user can act on. Same for the staging directory, where a killed task never
reached the `finally` that deletes the upload.

This assumes the single-worker deployment the Dockerfile runs. Under multiple
workers a fresh worker would clean up a sibling's in-flight work, so that setup
needs a real queue with per-task ownership instead.
"""
from __future__ import annotations

from sqlalchemy import select, update

from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.services.ingestion import upload_dir

logger = get_logger(__name__)

INTERRUPTED_REASON = (
    "Processing stopped when the server restarted. Please upload the file again."
)


async def recover_interrupted_ingestions() -> int:
    """Fail every document left on `processing`. Returns how many were reset."""
    async with AsyncSessionLocal() as session:
        stuck = (
            await session.execute(
                select(Document.id).where(Document.status == DocumentStatus.processing)
            )
        ).scalars().all()

        if not stuck:
            return 0

        await session.execute(
            update(Document)
            .where(Document.status == DocumentStatus.processing)
            .values(status=DocumentStatus.failed, error_reason=INTERRUPTED_REASON)
        )
        await session.commit()

    logger.warning(
        "marked interrupted ingestions as failed",
        extra={"documents": len(stuck)},
    )
    return len(stuck)


def sweep_staging_dir() -> int:
    """
    Delete uploads the previous process left behind. Returns how many were removed.

    A staged file is only reachable through the path handed to its background
    task, so once that process is gone nothing can claim it. Retrying is not an
    option either: the filename is a random UUID with no link back to a document
    row, so the user has to re-upload.
    """
    removed = 0
    for leftover in upload_dir().iterdir():
        if not leftover.is_file():
            continue
        try:
            leftover.unlink()
            removed += 1
        except OSError as exc:
            logger.warning(
                "could not delete staged upload",
                extra={"path": str(leftover), "error": str(exc)},
            )

    if removed:
        logger.info("cleared staged uploads", extra={"files": removed})
    return removed
