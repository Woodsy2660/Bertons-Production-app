"""Regression: concurrent add_reading never duplicates sequence (TEST-C1 / QA-001)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Batch, BatchHeader, BatchStatus, FormInstance, FormType as ModelFormType, Reading
from app.services.form_persistence import add_reading


def test_concurrent_add_reading_unique_contiguous_sequences():
    asyncio.run(_run())


async def _run() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_size=20, max_overflow=10)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        batch = Batch(
            run_number=f"SEQ-{uuid.uuid4().hex[:8]}",
            status=BatchStatus.IN_PROGRESS,
            created_by="pytest",
        )
        db.add(batch)
        await db.flush()
        db.add(
            BatchHeader(
                batch_id=batch.id,
                product="Test",
                run_date=date.today(),
            )
        )
        await db.commit()
        batch_id = batch.id

    async def one(i: int) -> None:
        async with Session() as db:
            batch = (
                await db.execute(select(Batch).where(Batch.id == batch_id))
            ).scalar_one()
            await add_reading(
                db,
                batch,
                "bottle_sealing",
                operator_identifier=f"op{i}",
                captured_at=None,
                payload={"note": f"n{i}"},
                role="operator",
            )

    await asyncio.gather(*[one(i) for i in range(20)])

    async with Session() as db:
        fi = (
            await db.execute(
                select(FormInstance).where(
                    FormInstance.batch_id == batch_id,
                    FormInstance.form_type == ModelFormType.BOTTLE_SEALING,
                )
            )
        ).scalar_one()
        rows = (
            await db.execute(
                select(Reading)
                .where(Reading.form_instance_id == fi.id)
                .order_by(Reading.sequence)
            )
        ).scalars().all()
        sequences = [r.sequence for r in rows]
        assert len(sequences) == 20
        assert sequences == list(range(1, 21))
        assert len(set(sequences)) == 20

    await engine.dispose()
