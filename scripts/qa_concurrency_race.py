"""
TEST_PLAN §2.10 — Concurrency & race-condition testing (live).

Opens concurrent operator + manager sessions against one in-progress batch,
floods the same accrual form with append-only readings, optionally races
two compile POSTs on an awaiting_review batch, and reports PASS/FAIL.

Usage:
  python scripts/qa_concurrency_race.py --base-url http://127.0.0.1:8001
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

DEFAULT_BASE = "http://127.0.0.1:8001"
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = WORKSPACE_ROOT / "qa_concurrency_results.md"

# Prefer append-only log forms (safer than atomic overwrite races).
ACCRUAL_FORM_CANDIDATES = ("bottle_sealing", "carton_qc")
UUID_RE = re.compile(
    r"/batches/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.I,
)


@dataclass
class WriteResult:
    session_id: int
    role: str
    status: int | None
    ok_2xx: bool
    is_5xx: bool
    error: str | None = None
    reading_id: str | None = None
    reading_count: int | None = None
    sequence: int | None = None
    latency_ms: float = 0.0


@dataclass
class SessionPageHit:
    session_id: int
    role: str
    path: str
    status: int | None
    error: str | None = None


@dataclass
class CompileRaceResult:
    skipped: bool
    reason: str = ""
    batch_id: str | None = None
    statuses: list[int] = field(default_factory=list)
    bodies: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def timed(
    client: httpx.AsyncClient, method: str, url: str, **kwargs
) -> tuple[httpx.Response, float]:
    start = time.perf_counter()
    resp = await client.request(method, url, **kwargs)
    return resp, (time.perf_counter() - start) * 1000


async def login(
    client: httpx.AsyncClient, base: str, username: str, password: str
) -> httpx.Response:
    r, _ = await timed(
        client,
        "POST",
        f"{base}/login",
        data={"username": username, "password": password, "next": "/"},
        follow_redirects=False,
    )
    return r


def unique_ids(html: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for bid in UUID_RE.findall(html):
        low = bid.lower()
        if low not in seen:
            seen.add(low)
            out.append(low)
    return out


async def discover_batches(
    base: str, username: str, password: str
) -> dict[str, list[str]]:
    """Return {in_progress: [...], awaiting_review: [...], all: [...]} from dashboard."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await login(client, base, username, password)
        r = await client.get(f"{base}/")
        if r.status_code != 200:
            return {"in_progress": [], "awaiting_review": [], "all": []}

        html = r.text
        # Split dashboard sections roughly by heading markers in HTML.
        in_progress: list[str] = []
        awaiting: list[str] = []

        # Active Runs section cards are tagged --in-progress; review uses --review
        # Pair each card link with nearest status class by walking run-card blocks.
        cards = re.findall(
            r'<a href="/batches/([0-9a-f-]{36})" class="run-card">(.*?)</a>',
            html,
            flags=re.I | re.S,
        )
        for bid, body in cards:
            bid = bid.lower()
            if "run-card-status--in-progress" in body:
                in_progress.append(bid)
            elif "run-card-status--review" in body:
                awaiting.append(bid)

        all_ids = unique_ids(html)
        # Fallback: if card parse failed, treat first all_ids as candidates.
        if not in_progress and not awaiting:
            in_progress = all_ids[:1]

        return {
            "in_progress": list(dict.fromkeys(in_progress)),
            "awaiting_review": list(dict.fromkeys(awaiting)),
            "all": all_ids,
        }


def reading_payload(form_type: str, session_id: int, tag: str) -> dict:
    """Append-only reading body with unique marker for lost-update observation."""
    marker = f"QA-RACE-{tag}-{session_id}-{uuid.uuid4().hex[:10]}"
    if form_type == "carton_qc":
        return {
            "operator_identifier": f"QA-OP-{session_id}",
            "table": "carton_details",
            "carton_manufacturer": "QA Concurrent",
            "carton_code": marker,
            "qty_on_pallet": "10",
            "carton_code_match": "Y",
            "batch_number_pallet_tag": marker,
            "dividers_match": "NA",
            "stickers_match": "NA",
            "initials": f"Q{session_id % 100}",
        }
    # bottle_sealing (default)
    return {
        "operator_identifier": f"QA-OP-{session_id}",
        "captured_at": "12:34",
        "batch_number": marker,
        "matches_work_order": "Y",
        "qty_used": "1",
        "initial": f"Q{session_id % 100}",
    }


async def session_worker(
    *,
    session_id: int,
    role: str,
    username: str,
    password: str,
    base: str,
    batch_id: str,
    form_type: str,
    write_rounds: int,
    timeout: float,
    barrier: asyncio.Barrier,
    page_hits: list[SessionPageHit],
    writes: list[WriteResult],
    tag: str,
) -> None:
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    async with httpx.AsyncClient(
        timeout=timeout, limits=limits, follow_redirects=False
    ) as client:
        try:
            r = await login(client, base, username, password)
            if r.status_code not in (200, 303):
                page_hits.append(
                    SessionPageHit(
                        session_id, role, "/login", r.status_code, "login failed"
                    )
                )
                # Still wait so others are not stuck on barrier forever.
                try:
                    await barrier.wait()
                except asyncio.BrokenBarrierError:
                    pass
                return

            # Hit dashboard + batch detail + form page before the write wave.
            for path in (
                "/",
                f"/batches/{batch_id}",
                f"/batches/{batch_id}/forms/{form_type}",
            ):
                try:
                    resp, _ = await timed(client, "GET", f"{base}{path}")
                    page_hits.append(
                        SessionPageHit(session_id, role, path, resp.status_code)
                    )
                except Exception as exc:  # noqa: BLE001
                    page_hits.append(
                        SessionPageHit(
                            session_id, role, path, None, f"{type(exc).__name__}: {exc}"
                        )
                    )

            # Align all sessions before the concurrent write storm.
            try:
                await barrier.wait()
            except asyncio.BrokenBarrierError:
                return

            for round_i in range(write_rounds):
                body = reading_payload(form_type, session_id, f"{tag}-r{round_i}")
                url = f"{base}/api/batches/{batch_id}/forms/{form_type}/readings"
                try:
                    resp, ms = await timed(client, "POST", url, json=body)
                    reading_id = None
                    reading_count = None
                    sequence = None
                    if resp.headers.get("content-type", "").startswith(
                        "application/json"
                    ):
                        try:
                            data = resp.json()
                            reading = data.get("reading") or {}
                            reading_id = reading.get("id")
                            sequence = reading.get("sequence")
                            reading_count = data.get("reading_count")
                        except Exception:  # noqa: BLE001
                            pass
                    writes.append(
                        WriteResult(
                            session_id=session_id,
                            role=role,
                            status=resp.status_code,
                            ok_2xx=200 <= resp.status_code < 300,
                            is_5xx=resp.status_code >= 500,
                            reading_id=reading_id,
                            reading_count=reading_count,
                            sequence=sequence,
                            latency_ms=ms,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    writes.append(
                        WriteResult(
                            session_id=session_id,
                            role=role,
                            status=None,
                            ok_2xx=False,
                            is_5xx=False,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            page_hits.append(
                SessionPageHit(
                    session_id, role, "session", None, f"{type(exc).__name__}: {exc}"
                )
            )
            try:
                await barrier.wait()
            except asyncio.BrokenBarrierError:
                pass


async def simultaneous_compile_race(
    base: str,
    batch_id: str,
    username: str,
    password: str,
    timeout: float,
) -> CompileRaceResult:
    """Fire two concurrent manager compile POSTs at the same batch."""
    barrier = asyncio.Barrier(2)
    results: list[tuple[int | None, str, str | None]] = []

    async def one(worker_id: int) -> None:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            try:
                r = await login(client, base, username, password)
                if r.status_code not in (200, 303):
                    results.append((r.status_code, "", f"login failed worker {worker_id}"))
                    try:
                        await barrier.wait()
                    except asyncio.BrokenBarrierError:
                        pass
                    return
                await barrier.wait()
                resp, _ = await timed(
                    client, "POST", f"{base}/batches/{batch_id}/compile"
                )
                body_snip = (resp.text or "")[:200].replace("\n", " ")
                results.append((resp.status_code, body_snip, None))
            except Exception as exc:  # noqa: BLE001
                results.append((None, "", f"{type(exc).__name__}: {exc}"))
                try:
                    await barrier.wait()
                except asyncio.BrokenBarrierError:
                    pass

    await asyncio.gather(one(0), one(1))
    return CompileRaceResult(
        skipped=False,
        batch_id=batch_id,
        statuses=[s for s, _, _ in results if s is not None],
        bodies=[b for _, b, _ in results if b],
        errors=[e for _, _, e in results if e],
    )


def build_report(
    *,
    base: str,
    batch_id: str | None,
    form_type: str,
    n_ops: int,
    n_mgrs: int,
    write_rounds: int,
    page_hits: list[SessionPageHit],
    writes: list[WriteResult],
    compile_race: CompileRaceResult,
    pre_health: int,
    pre_ready: int,
    post_health: int,
    post_ready: int,
    wall_s: float,
    pass_fail: str,
    criteria: list[tuple[str, bool, str]],
) -> str:
    codes = Counter(w.status for w in writes if w.status is not None)
    ok_2xx = sum(1 for w in writes if w.ok_2xx)
    n_5xx = sum(1 for w in writes if w.is_5xx)
    total_writes = len(writes)
    write_rate = (ok_2xx / total_writes) if total_writes else 0.0
    page_5xx = sum(1 for p in page_hits if p.status is not None and p.status >= 500)
    page_codes = Counter(p.status for p in page_hits if p.status is not None)

    sequences = [w.sequence for w in writes if w.ok_2xx and w.sequence is not None]
    seq_counter = Counter(sequences)
    dup_sequences = {s: c for s, c in seq_counter.items() if c > 1}
    unique_reading_ids = {w.reading_id for w in writes if w.ok_2xx and w.reading_id}
    max_reported_count = max(
        (w.reading_count for w in writes if w.reading_count is not None), default=None
    )

    latencies = [w.latency_ms for w in writes if w.latency_ms > 0]
    lat_line = "n/a"
    if latencies:
        lat_line = (
            f"n={len(latencies)} min={min(latencies):.0f}ms "
            f"median={sorted(latencies)[len(latencies)//2]:.0f}ms "
            f"max={max(latencies):.0f}ms"
        )

    lines = [
        "# QA Concurrency & Race Conditions — Results",
        "",
        f"**Plan:** TEST_PLAN §2.10  ",
        f"**Generated:** {_now_iso()}  ",
        f"**Target:** `{base}`  ",
        f"**Overall:** **{pass_fail}**  ",
        f"**Wall clock:** {wall_s:.2f}s  ",
        "",
        "## Setup",
        "",
        f"- Operator sessions: **{n_ops}**",
        f"- Manager sessions: **{n_mgrs}**",
        f"- Target batch (in-progress): `{batch_id or 'NONE'}`",
        f"- Accrual form type: `{form_type}`",
        f"- Write rounds per session: **{write_rounds}**",
        f"- Expected write attempts: **{n_ops + n_mgrs} × {write_rounds} = {(n_ops + n_mgrs) * write_rounds}**",
        f"- Write style: append-only accrual readings (no deletes, no atomic overwrite)",
        "",
        "## Pre / post health",
        "",
        f"| Probe | Pre | Post |",
        f"|-------|-----|------|",
        f"| `/health` | {pre_health} | {post_health} |",
        f"| `/ready` | {pre_ready} | {post_ready} |",
        "",
        "## Form page hits (all sessions → same batch)",
        "",
        f"- Samples: {len(page_hits)}",
        f"- Status codes: `{dict(page_codes)}`",
        f"- HTTP 5xx on page GETs: **{page_5xx}**",
        "",
        "## Concurrent accrual writes",
        "",
        f"- Attempts: **{total_writes}**",
        f"- 2xx successes: **{ok_2xx}** ({write_rate:.1%})",
        f"- HTTP 5xx: **{n_5xx}**",
        f"- Status codes: `{dict(codes)}`",
        f"- Write latency: {lat_line}",
        "",
        "### Lost-update / consistency observation",
        "",
        "Accrual writes are append-only; a pure lost-update would appear as fewer "
        "persisted rows than successful 2xx responses, or duplicate `sequence` values "
        "if sequence assignment races without locking.",
        "",
        f"- Successful 2xx writes: **{ok_2xx}**",
        f"- Unique reading IDs returned: **{len(unique_reading_ids)}**",
        f"- Max `reading_count` reported in responses: **{max_reported_count}**",
        f"- Sequences returned (value→count): `{dict(sorted(seq_counter.items())) if seq_counter else {}}`",
        f"- Duplicate sequences among successes: "
        f"**{len(dup_sequences)}** "
        f"({dict(sorted(dup_sequences.items())) if dup_sequences else 'none'})",
        "",
    ]

    if ok_2xx and len(unique_reading_ids) < ok_2xx:
        lines.append(
            f"- **Observation:** fewer unique reading IDs ({len(unique_reading_ids)}) "
            f"than 2xx writes ({ok_2xx}) — possible response reuse or silent drop."
        )
    elif dup_sequences:
        lines.append(
            "- **Observation:** duplicate sequence numbers across concurrent inserts "
            "indicate a sequence-assignment race (no unique constraint on "
            "`(form_instance_id, sequence)`). Rows may still exist; ordering/PDF "
            "numbering may be inconsistent."
        )
    elif ok_2xx:
        lines.append(
            "- **Observation:** each 2xx returned a distinct reading id; no duplicate "
            "sequences observed in this run. Lost-update risk for append-only path "
            "looks low under this load (sequence uniqueness not DB-enforced)."
        )
    else:
        lines.append("- **Observation:** no successful writes to analyse.")

    lines += [
        "",
        "## Simultaneous compile race",
        "",
    ]
    if compile_race.skipped:
        lines.append(f"- **SKIPPED:** {compile_race.reason}")
    else:
        lines += [
            f"- Batch: `{compile_race.batch_id}`",
            f"- Statuses: `{compile_race.statuses}`",
            f"- Errors: `{compile_race.errors or 'none'}`",
            f"- Body snippets: `{compile_race.bodies}`",
            "",
            "Expected healthy behaviour: one compile succeeds (2xx/3xx redirect) and "
            "the second is rejected cleanly (4xx or controlled redirect with error) "
            "without 500s or double-complete corruption.",
        ]
        compile_5xx = sum(1 for s in compile_race.statuses if s >= 500)
        lines.append(f"- Compile HTTP 5xx count: **{compile_5xx}**")

    lines += [
        "",
        "## Pass criteria",
        "",
        "| Criterion | Result | Detail |",
        "|-----------|--------|--------|",
    ]
    for name, ok, detail in criteria:
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")

    lines += [
        "",
        f"## Overall: {pass_fail}",
        "",
        "### Notes",
        "",
        "- Shared credentials (`operator`/`manager`) with separate cookie jars simulate "
        "multiple devices under shared logins.",
        "- Reads target a single in-progress batch; writes only append readings.",
        "- This script does not delete data and does not force batch status changes "
        "except optional compile race on an already awaiting_review batch.",
        "",
    ]
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> int:
    base = args.base_url.rstrip("/")
    n_ops = args.operators
    n_mgrs = args.managers
    write_rounds = args.write_rounds
    total_sessions = n_ops + n_mgrs
    form_type = args.form_type
    tag = uuid.uuid4().hex[:6]

    print(f"Target:     {base}")
    print(f"Sessions:   {n_ops} operators + {n_mgrs} managers = {total_sessions}")
    print(f"Form type:  {form_type}")
    print(f"Writes/sess:{write_rounds}")

    async with httpx.AsyncClient(timeout=15.0) as client:
        pre_h = await client.get(f"{base}/health")
        pre_r = await client.get(f"{base}/ready")
        print(f"Preflight:  health={pre_h.status_code} ready={pre_r.status_code}")
        if pre_h.status_code != 200 or pre_r.status_code != 200:
            report = (
                f"# QA Concurrency — ABORT\n\n"
                f"App not healthy/ready at `{base}` "
                f"(health={pre_h.status_code}, ready={pre_r.status_code}).\n"
            )
            RESULTS_PATH.write_text(report, encoding="utf-8")
            print("ABORT: app not healthy/ready")
            print("OVERALL: FAIL")
            return 2

    batches = await discover_batches(
        base, args.manager_user, args.manager_pass
    )
    in_progress = batches["in_progress"]
    awaiting = batches["awaiting_review"]
    print(
        f"Discovered: in_progress={len(in_progress)} "
        f"awaiting_review={len(awaiting)} all={len(batches['all'])}"
    )

    if not in_progress:
        report = (
            f"# QA Concurrency — ABORT\n\n"
            f"No in-progress batch found on dashboard at `{base}`.\n"
        )
        RESULTS_PATH.write_text(report, encoding="utf-8")
        print("ABORT: no in-progress batch")
        print("OVERALL: FAIL")
        return 2

    batch_id = in_progress[0]
    print(f"Using batch: {batch_id}")

    # Prefer requested form; if forced invalid, still use it and observe errors.
    if form_type not in ACCRUAL_FORM_CANDIDATES:
        print(
            f"WARN: form_type={form_type} not in preferred {ACCRUAL_FORM_CANDIDATES}; "
            "proceeding anyway"
        )

    page_hits: list[SessionPageHit] = []
    writes: list[WriteResult] = []
    barrier = asyncio.Barrier(total_sessions)

    tasks = []
    for i in range(n_ops):
        tasks.append(
            session_worker(
                session_id=i,
                role="operator",
                username=args.operator_user,
                password=args.operator_pass,
                base=base,
                batch_id=batch_id,
                form_type=form_type,
                write_rounds=write_rounds,
                timeout=args.timeout,
                barrier=barrier,
                page_hits=page_hits,
                writes=writes,
                tag=tag,
            )
        )
    for j in range(n_mgrs):
        tasks.append(
            session_worker(
                session_id=n_ops + j,
                role="manager",
                username=args.manager_user,
                password=args.manager_pass,
                base=base,
                batch_id=batch_id,
                form_type=form_type,
                write_rounds=write_rounds,
                timeout=args.timeout,
                barrier=barrier,
                page_hits=page_hits,
                writes=writes,
                tag=tag,
            )
        )

    t0 = time.perf_counter()
    await asyncio.gather(*tasks)

    # Simultaneous compile race (awaiting_review only).
    if awaiting:
        compile_batch = awaiting[0]
        print(f"Compile race on awaiting_review batch: {compile_batch}")
        compile_race = await simultaneous_compile_race(
            base,
            compile_batch,
            args.manager_user,
            args.manager_pass,
            timeout=max(args.timeout, 60.0),
        )
    else:
        compile_race = CompileRaceResult(
            skipped=True,
            reason="No awaiting_review batch on dashboard; compile race not run.",
        )
        print("Compile race: SKIPPED (no awaiting_review batch)")

    wall = time.perf_counter() - t0

    async with httpx.AsyncClient(timeout=15.0) as client:
        post_h = await client.get(f"{base}/health")
        post_r = await client.get(f"{base}/ready")
        print(f"Postflight: health={post_h.status_code} ready={post_r.status_code}")

    total_writes = len(writes)
    ok_2xx = sum(1 for w in writes if w.ok_2xx)
    n_5xx_writes = sum(1 for w in writes if w.is_5xx)
    page_5xx = sum(1 for p in page_hits if p.status is not None and p.status >= 500)
    write_non5xx_rate = (
        sum(1 for w in writes if w.status is not None and w.status < 500) / total_writes
        if total_writes
        else 0.0
    )
    # Spec: "at least 80% of writes return non-5xx"
    non5xx_ok = write_non5xx_rate >= 0.80
    no_5xx = (n_5xx_writes + page_5xx) == 0
    # Also count compile 5xx
    compile_5xx = (
        0
        if compile_race.skipped
        else sum(1 for s in compile_race.statuses if s >= 500)
    )
    no_5xx = no_5xx and compile_5xx == 0
    health_ok = post_h.status_code == 200 and post_r.status_code == 200

    criteria = [
        (
            "No HTTP 500s (pages + writes + compile)",
            no_5xx,
            f"write_5xx={n_5xx_writes} page_5xx={page_5xx} compile_5xx={compile_5xx}",
        ),
        (
            "Postflight /health and /ready == 200",
            health_ok,
            f"health={post_h.status_code} ready={post_r.status_code}",
        ),
        (
            "≥80% of writes return non-5xx",
            non5xx_ok,
            f"{write_non5xx_rate:.1%} ({ok_2xx} 2xx / {total_writes} attempts; "
            f"non5xx_rate={write_non5xx_rate:.1%})",
        ),
        (
            "Sessions opened (10 op + 5 mgr defaults)",
            total_sessions >= 15,
            f"sessions={total_sessions}",
        ),
        (
            "In-progress batch targeted",
            batch_id is not None,
            f"batch={batch_id}",
        ),
    ]

    overall_pass = all(ok for _, ok, _ in criteria)
    pass_fail = "PASS" if overall_pass else "FAIL"

    report = build_report(
        base=base,
        batch_id=batch_id,
        form_type=form_type,
        n_ops=n_ops,
        n_mgrs=n_mgrs,
        write_rounds=write_rounds,
        page_hits=page_hits,
        writes=writes,
        compile_race=compile_race,
        pre_health=pre_h.status_code,
        pre_ready=pre_r.status_code,
        post_health=post_h.status_code,
        post_ready=post_r.status_code,
        wall_s=wall,
        pass_fail=pass_fail,
        criteria=criteria,
    )
    RESULTS_PATH.write_text(report, encoding="utf-8")
    print(f"Wrote: {RESULTS_PATH}")

    print("\n========== CONCURRENCY RACE SUMMARY ==========")
    print(f"Writes:     {ok_2xx}/{total_writes} 2xx  5xx={n_5xx_writes}")
    print(f"Non-5xx %:  {write_non5xx_rate:.1%}")
    print(f"Page 5xx:   {page_5xx}")
    if compile_race.skipped:
        print(f"Compile:    SKIPPED — {compile_race.reason}")
    else:
        print(f"Compile:    statuses={compile_race.statuses}")
    for name, ok, detail in criteria:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    print(f"\nOVERALL: {pass_fail}")
    return 0 if overall_pass else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Berton QA concurrency / race test (§2.10)")
    p.add_argument("--base-url", default=DEFAULT_BASE)
    p.add_argument("--operators", type=int, default=10)
    p.add_argument("--managers", type=int, default=5)
    p.add_argument("--write-rounds", type=int, default=1)
    p.add_argument(
        "--form-type",
        default="bottle_sealing",
        choices=["bottle_sealing", "carton_qc"],
    )
    p.add_argument("--timeout", type=float, default=45.0)
    p.add_argument("--manager-user", default="manager")
    p.add_argument("--manager-pass", default="manager")
    p.add_argument("--operator-user", default="operator")
    p.add_argument("--operator-pass", default="operator")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        raise SystemExit(asyncio.run(main_async(args)))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
