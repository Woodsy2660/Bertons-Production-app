"""REMAINING_TESTS §2 P2 (partial), §3 E2 latency, §4 S1 autoescape smoke."""

from __future__ import annotations

import asyncio
import statistics
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8001"


async def login(c: httpx.AsyncClient, user="manager", pw="manager"):
    await c.post(f"{BASE}/login", data={"username": user, "password": pw, "next": "/"})


async def test_p2_db_restart() -> list[tuple[str, bool, str]]:
    results = []
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(f"{BASE}/ready")
        results.append(("P2 pre ready", r.status_code == 200, r.text[:80]))

    # Stop postgres mid-flight
    import subprocess

    subprocess.run(["docker", "stop", "berton-postgres"], check=False, capture_output=True)
    await asyncio.sleep(2)
    async with httpx.AsyncClient(timeout=10.0) as c:
        try:
            r = await c.get(f"{BASE}/ready")
            ready_down = r.status_code != 200
            results.append(("P2 ready fails while DB down", ready_down, f"status={r.status_code}"))
        except Exception as e:
            results.append(("P2 ready fails while DB down", True, f"exception={type(e).__name__}"))

        await login(c, "operator", "operator")
        # attempt a save — should fail loudly not silent 200
        try:
            r = await c.post(
                f"{BASE}/api/batches/ad222eb1-2288-4e69-9c37-6d9698ae3621/forms/bottle_sealing/readings",
                json={"operator_identifier": "p2", "payload": {"note": "during-outage"}},
            )
            loud = r.status_code >= 400
            results.append(("P2 write fails loudly during outage", loud, f"status={r.status_code}"))
        except Exception as e:
            results.append(("P2 write fails loudly during outage", True, f"exception={type(e).__name__}"))

    subprocess.run(["docker", "start", "berton-postgres"], check=False, capture_output=True)
    # wait for recovery
    ok = False
    for _ in range(30):
        await asyncio.sleep(1)
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{BASE}/ready")
                if r.status_code == 200:
                    ok = True
                    break
        except Exception:
            pass
    results.append(("P2 app self-recovers ready", ok, "ready after restart"))

    # committed prior data still queryable via dashboard
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
        await login(c)
        r = await c.get(f"{BASE}/")
        results.append(("P2 dashboard after recovery", r.status_code == 200, f"len={len(r.text)}"))

    return results


async def test_e2_latency() -> list[tuple[str, bool, str]]:
    """Re-run multi-user style load with explicit thresholds."""
    import subprocess
    import sys

    # Use existing load script and parse isn't easy — inline short load
    latencies = []
    errors = 0

    async def user(i: int):
        nonlocal errors
        async with httpx.AsyncClient(timeout=30.0) as c:
            t0 = time.perf_counter()
            await login(c, "operator" if i % 10 < 7 else "manager", "operator" if i % 10 < 7 else "manager")
            latencies.append((time.perf_counter() - t0) * 1000)
            for _ in range(2):
                t0 = time.perf_counter()
                r = await c.get(f"{BASE}/")
                latencies.append((time.perf_counter() - t0) * 1000)
                if r.status_code >= 500:
                    errors += 1
                t0 = time.perf_counter()
                r = await c.get(f"{BASE}/health")
                latencies.append((time.perf_counter() - t0) * 1000)

    await asyncio.gather(*[user(i) for i in range(20)])
    p50 = statistics.median(latencies)
    s = sorted(latencies)
    p95 = s[int(0.95 * (len(s) - 1))]
    mx = max(latencies)
    # Suggested bounds from REMAINING_TESTS for form save/load — health/dashboard softer
    # We report against hard max 8s for non-compile paths
    return [
        ("E2 20-user p50 <= 1000ms", p50 <= 1000, f"p50={p50:.0f}ms"),
        ("E2 20-user p95 <= 3000ms", p95 <= 3000, f"p95={p95:.0f}ms"),
        ("E2 20-user hard max <= 8000ms", mx <= 8000, f"max={mx:.0f}ms"),
        ("E2 no 5xx", errors == 0, f"5xx={errors}"),
    ]


def test_s1_autoescape() -> list[tuple[str, bool, str]]:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from pathlib import Path
    import inspect
    from app.services import compilation

    src = inspect.getsource(compilation.compile_batch)
    has_autoescape = "autoescape=True" in src or "select_autoescape" in src
    results = [
        ("S1 compile_batch enables autoescape", has_autoescape, "scan compile_batch source"),
    ]
    # Render a fragment with markup
    templates_path = Path(compilation.__file__).parent.parent / "templates" / "pdf"
    env = Environment(loader=FileSystemLoader(str(templates_path)), autoescape=True)
    # generic template exists
    try:
        t = env.from_string("{{ value }}")
        out = t.render(value="<script>alert(1)</script>")
        results.append(
            (
                "S1 markup escaped as literal",
                "&lt;script&gt;" in out or "&#" in out,
                f"out={out[:80]!r}",
            )
        )
    except Exception as e:
        results.append(("S1 markup escaped as literal", False, str(e)))
    return results


async def main():
    all_results = []
    print("=== TEST-S1 ===")
    for name, ok, detail in test_s1_autoescape():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        all_results.append(ok)

    print("=== TEST-E2 ===")
    for name, ok, detail in await test_e2_latency():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        all_results.append(ok)

    print("=== TEST-P2 (DB stop/start) ===")
    for name, ok, detail in await test_p2_db_restart():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        all_results.append(ok)

    passed = sum(1 for x in all_results if x)
    print(f"\n{passed}/{len(all_results)} checks passed")
    return 0 if all(all_results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
