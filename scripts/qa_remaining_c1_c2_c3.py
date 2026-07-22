"""
REMAINING_TESTS §1 — data-level concurrency assertions (TEST-C1, C2, C3).

Asserts on database state, not HTTP status codes.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from collections import Counter
from dataclasses import dataclass

import httpx
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models import Reading, FormInstance, Compilation, Batch, BatchStatus

DEFAULT_BASE = "http://127.0.0.1:8001"


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def report(results: list[CheckResult]) -> int:
    for r in results:
        flag = "PASS" if r.passed else "FAIL"
        print(f"  [{flag}] {r.name}: {r.detail}")
    fails = [r for r in results if not r.passed]
    print(f"\n{len(results) - len(fails)}/{len(results)} checks passed")
    return 0 if not fails else 1


async def login(client: httpx.AsyncClient, base: str, user: str, password: str) -> None:
    r = await client.post(
        f"{base}/login",
        data={"username": user, "password": password, "next": "/"},
        follow_redirects=False,
    )
    if r.status_code not in (200, 303):
        raise RuntimeError(f"login failed {user}: {r.status_code}")


async def discover_in_progress_batch(base: str, user: str, password: str) -> str | None:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await login(client, base, user, password)
        r = await client.get(f"{base}/")
        ids = re.findall(
            r"/batches/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
            r.text,
        )
        return ids[0] if ids else None


async def test_c1_sequence_integrity(base: str, args: argparse.Namespace) -> list[CheckResult]:
    print("\n=== TEST-C1 Accrual sequence integrity ===")
    results: list[CheckResult] = []
    n = args.sessions
    form_type = args.form_type
    iterations = args.iterations

    batch_id = await discover_in_progress_batch(
        base, args.manager_user, args.manager_pass
    )
    if not batch_id:
        return [CheckResult("C1 setup", False, "no batch found on dashboard")]

    # Snapshot sequences before
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as db:
        fi = (
            await db.execute(
                select(FormInstance).where(
                    FormInstance.batch_id == uuid.UUID(batch_id),
                    FormInstance.form_type == form_type,
                )
            )
        ).scalar_one_or_none()
        before_count = 0
        if fi:
            before_count = (
                await db.execute(
                    select(func.count()).select_from(Reading).where(
                        Reading.form_instance_id == fi.id
                    )
                )
            ).scalar_one()

    async def one_write(i: int) -> tuple[int, str | None]:
        role_user = (
            (args.manager_user, args.manager_pass)
            if i % 10 >= 7
            else (args.operator_user, args.operator_pass)
        )
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=False) as client:
            await login(client, base, role_user[0], role_user[1])
            r = await client.post(
                f"{base}/api/batches/{batch_id}/forms/{form_type}/readings",
                json={
                    "operator_identifier": f"c1-u{i}",
                    "payload": {"note": f"c1-{i}-{uuid.uuid4().hex[:8]}"},
                },
            )
            rid = None
            if r.status_code < 500:
                try:
                    rid = r.json().get("id") or r.json().get("reading", {}).get("id")
                except Exception:
                    rid = None
            return r.status_code, rid

    success_posts = 0
    for round_i in range(iterations):
        tasks = [one_write(round_i * n + i) for i in range(n)]
        outcomes = await asyncio.gather(*tasks)
        for code, _ in outcomes:
            if 200 <= code < 300:
                success_posts += 1
            elif code >= 500:
                results.append(
                    CheckResult(
                        f"C1 no 5xx round {round_i}",
                        False,
                        f"got {code}",
                    )
                )

    # Data-level asserts
    async with session_maker() as db:
        fi = (
            await db.execute(
                select(FormInstance).where(
                    FormInstance.batch_id == uuid.UUID(batch_id),
                    FormInstance.form_type == form_type,
                )
            )
        ).scalar_one_or_none()
        if not fi:
            await engine.dispose()
            return [CheckResult("C1 form instance", False, "form instance missing after writes")]

        rows = (
            await db.execute(
                select(Reading)
                .where(Reading.form_instance_id == fi.id)
                .order_by(Reading.sequence, Reading.created_at)
            )
        ).scalars().all()

        after_count = len(rows)
        added = after_count - before_count
        sequences = [r.sequence for r in rows]
        seq_counts = Counter(sequences)
        duplicates = {s: c for s, c in seq_counts.items() if c > 1}
        expected_contig = list(range(1, after_count + 1))
        actual_sorted = sorted(sequences)

        results.append(
            CheckResult(
                "C1 unique sequences",
                len(duplicates) == 0,
                f"duplicates={duplicates or 'none'}; n={after_count}",
            )
        )
        results.append(
            CheckResult(
                "C1 contiguous 1..M",
                actual_sorted == expected_contig,
                f"got={actual_sorted[:20]}{'...' if after_count > 20 else ''}",
            )
        )
        results.append(
            CheckResult(
                "C1 row count == successful POSTs (+ prior)",
                added == success_posts,
                f"added={added} success_posts={success_posts} before={before_count} after={after_count}",
            )
        )
        # Deterministic re-read order
        reread = (
            await db.execute(
                select(Reading)
                .where(Reading.form_instance_id == fi.id)
                .order_by(Reading.sequence)
            )
        ).scalars().all()
        results.append(
            CheckResult(
                "C1 stable re-read order",
                [r.id for r in rows] == [r.id for r in reread]
                and [r.sequence for r in reread] == expected_contig,
                f"sequences={[r.sequence for r in reread[:15]]}",
            )
        )

    await engine.dispose()
    return results


async def test_c2_single_compilation(base: str, args: argparse.Namespace) -> list[CheckResult]:
    print("\n=== TEST-C2 Single current compilation ===")
    results: list[CheckResult] = []
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Find a batch that is awaiting_review or reopened and has ezywine if possible
    async with session_maker() as db:
        batch = (
            await db.execute(
                select(Batch)
                .where(
                    Batch.status.in_(
                        [BatchStatus.AWAITING_REVIEW, BatchStatus.REOPENED, BatchStatus.IN_PROGRESS]
                    )
                )
                .order_by(Batch.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if not batch:
            await engine.dispose()
            return [CheckResult("C2 setup", False, "no suitable batch")]
        batch_id = str(batch.id)
        status_before = batch.status.value

    async def compile_once() -> int:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=False) as client:
            await login(client, base, args.manager_user, args.manager_pass)
            r = await client.post(f"{base}/batches/{batch_id}/compile")
            return r.status_code

    # 2 concurrent
    codes2 = await asyncio.gather(compile_once(), compile_once())
    async with session_maker() as db:
        current = (
            await db.execute(
                select(Compilation).where(
                    Compilation.batch_id == uuid.UUID(batch_id),
                    Compilation.is_current.is_(True),
                )
            )
        ).scalars().all()
        total = (
            await db.execute(
                select(func.count()).select_from(Compilation).where(
                    Compilation.batch_id == uuid.UUID(batch_id)
                )
            )
        ).scalar_one()
        batch = (
            await db.execute(select(Batch).where(Batch.id == uuid.UUID(batch_id)))
        ).scalar_one()

    # After successful compile path: exactly 0 or 1 current (0 if compile failed for missing ezywine)
    results.append(
        CheckResult(
            "C2 concurrent x2: at most one is_current",
            len(current) <= 1,
            f"current={len(current)} total_comps={total} codes={codes2} status={batch.status.value}",
        )
    )
    if any(c in (200, 303) for c in codes2) and batch.status == BatchStatus.COMPLETE:
        results.append(
            CheckResult(
                "C2 concurrent x2: exactly one current when complete",
                len(current) == 1,
                f"current={len(current)} codes={codes2}",
            )
        )
        # Losing request should be 409 or 303-to-error or second 303 after first won
        non_success_or_coalesced = sum(1 for c in codes2 if c in (303, 409, 400, 403))
        results.append(
            CheckResult(
                "C2 concurrent x2: losers deterministic (no 5xx)",
                all(c < 500 for c in codes2) and non_success_or_coalesced >= 1,
                f"codes={codes2}",
            )
        )

    # 5 concurrent only if still compilable or reopened - reopen if complete
    if batch.status == BatchStatus.COMPLETE:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            await login(client, base, args.manager_user, args.manager_pass)
            await client.post(f"{base}/batches/{batch_id}/reopen")

    codes5 = await asyncio.gather(*[compile_once() for _ in range(5)])
    async with session_maker() as db:
        current5 = (
            await db.execute(
                select(Compilation).where(
                    Compilation.batch_id == uuid.UUID(batch_id),
                    Compilation.is_current.is_(True),
                )
            )
        ).scalars().all()
        batch5 = (
            await db.execute(select(Batch).where(Batch.id == uuid.UUID(batch_id)))
        ).scalar_one()

    results.append(
        CheckResult(
            "C2 concurrent x5: at most one is_current",
            len(current5) <= 1,
            f"current={len(current5)} codes={codes5} status={batch5.status.value} prior={status_before}",
        )
    )
    if batch5.status == BatchStatus.COMPLETE:
        results.append(
            CheckResult(
                "C2 concurrent x5: exactly one current when complete",
                len(current5) == 1,
                f"current={len(current5)}",
            )
        )
        results.append(
            CheckResult(
                "C2 concurrent x5: no 5xx",
                all(c < 500 for c in codes5),
                f"codes={codes5}",
            )
        )

    await engine.dispose()
    return results


async def test_c3_cross_path(base: str, args: argparse.Namespace) -> list[CheckResult]:
    print("\n=== TEST-C3 Cross-path races ===")
    results: list[CheckResult] = []
    batch_id = await discover_in_progress_batch(
        base, args.manager_user, args.manager_pass
    )
    if not batch_id:
        return [CheckResult("C3 setup", False, "no batch")]

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    form_type = args.form_type

    async def save_reading() -> int:
        async with httpx.AsyncClient(timeout=45.0) as client:
            await login(client, base, args.operator_user, args.operator_pass)
            r = await client.post(
                f"{base}/api/batches/{batch_id}/forms/{form_type}/readings",
                json={
                    "operator_identifier": "c3-op",
                    "payload": {"note": f"c3-{uuid.uuid4().hex[:6]}"},
                },
            )
            return r.status_code

    async def compile_req() -> int:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=False) as client:
            await login(client, base, args.manager_user, args.manager_pass)
            r = await client.post(f"{base}/batches/{batch_id}/compile")
            return r.status_code

    async def reopen_req() -> int:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            await login(client, base, args.manager_user, args.manager_pass)
            r = await client.post(f"{base}/batches/{batch_id}/reopen")
            return r.status_code

    # Pair 1: compile racing accrual save
    c1, s1 = await asyncio.gather(compile_req(), save_reading())
    async with session_maker() as db:
        batch = (
            await db.execute(select(Batch).where(Batch.id == uuid.UUID(batch_id)))
        ).scalar_one()
        current = (
            await db.execute(
                select(func.count())
                .select_from(Compilation)
                .where(
                    Compilation.batch_id == uuid.UUID(batch_id),
                    Compilation.is_current.is_(True),
                )
            )
        ).scalar_one()
        # consistent: if COMPLETE, is_locked and at most one current; if not complete, writes may succeed
        locked_ok = (
            (batch.status == BatchStatus.COMPLETE and batch.is_locked and current <= 1)
            or (batch.status != BatchStatus.COMPLETE and current <= 1)
        )
        results.append(
            CheckResult(
                "C3 compile vs save: consistent terminal state",
                locked_ok and c1 < 500 and s1 < 500,
                f"status={batch.status.value} locked={batch.is_locked} current={current} codes=compile:{c1} save:{s1}",
            )
        )

    # Pair 2: reopen racing operator save (need complete first ideally)
    if batch.status != BatchStatus.COMPLETE:
        # try compile alone first
        await compile_req()

    r_code, s_code = await asyncio.gather(reopen_req(), save_reading())
    async with session_maker() as db:
        batch = (
            await db.execute(select(Batch).where(Batch.id == uuid.UUID(batch_id)))
        ).scalar_one()
        current = (
            await db.execute(
                select(func.count())
                .select_from(Compilation)
                .where(
                    Compilation.batch_id == uuid.UUID(batch_id),
                    Compilation.is_current.is_(True),
                )
            )
        ).scalar_one()
        # After reopen: REOPENED and no current; or still COMPLETE if reopen failed
        coherent = current <= 1 and r_code < 500 and s_code < 500
        if batch.status == BatchStatus.REOPENED:
            coherent = coherent and current == 0 and not batch.is_locked
        results.append(
            CheckResult(
                "C3 reopen vs save: coherent lock/state",
                coherent,
                f"status={batch.status.value} locked={batch.is_locked} current={current} reopen:{r_code} save:{s_code}",
            )
        )

    # Pair 3: reopen racing compile
    codes = await asyncio.gather(reopen_req(), compile_req())
    async with session_maker() as db:
        batch = (
            await db.execute(select(Batch).where(Batch.id == uuid.UUID(batch_id)))
        ).scalar_one()
        current = (
            await db.execute(
                select(func.count())
                .select_from(Compilation)
                .where(
                    Compilation.batch_id == uuid.UUID(batch_id),
                    Compilation.is_current.is_(True),
                )
            )
        ).scalar_one()
        # COMPLETE => exactly 1 current; REOPENED => 0 current; never >1
        if batch.status == BatchStatus.COMPLETE:
            ok = current == 1 and batch.is_locked
        elif batch.status == BatchStatus.REOPENED:
            ok = current == 0 and not batch.is_locked
        else:
            ok = current <= 1
        results.append(
            CheckResult(
                "C3 reopen vs compile: coherent",
                ok and all(c < 500 for c in codes),
                f"status={batch.status.value} current={current} codes={codes}",
            )
        )

    await engine.dispose()
    return results


async def main_async(args: argparse.Namespace) -> int:
    base = args.base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=10.0) as c:
        h = await c.get(f"{base}/health")
        r = await c.get(f"{base}/ready")
        print(f"Preflight health={h.status_code} ready={r.status_code}")
        if h.status_code != 200 or r.status_code != 200:
            print("ABORT: app not ready")
            return 2

    all_results: list[CheckResult] = []
    all_results.extend(await test_c1_sequence_integrity(base, args))
    all_results.extend(await test_c2_single_compilation(base, args))
    all_results.extend(await test_c3_cross_path(base, args))
    return report(all_results)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=DEFAULT_BASE)
    p.add_argument("--sessions", type=int, default=15)
    p.add_argument("--iterations", type=int, default=3)
    p.add_argument("--form-type", default="bottle_sealing")
    p.add_argument("--manager-user", default="manager")
    p.add_argument("--manager-pass", default="manager")
    p.add_argument("--operator-user", default="operator")
    p.add_argument("--operator-pass", default="operator")
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(parse_args())))
