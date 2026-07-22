"""
Multi-user concurrent load test against a running Berton app instance.

Simulates N concurrent sessions (operators + managers): login, dashboard,
batch detail, form pages, incremental form API writes, health probes.

Usage:
  python scripts/qa_multi_user_load.py --base-url http://127.0.0.1:8001 --users 20
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field

import httpx

DEFAULT_BASE = "http://127.0.0.1:8001"
FORM_TYPES = [
    "daily_production",
    "pick_list",
    "filler_line_check",
    "bottle_sealing",
    "label_usage",
    "finished_product_line_check",
    "carton_qc",
    "final_pallet_count",
    "finished_product_pallet",
]


@dataclass
class UserResult:
    user_id: int
    role: str
    ok: bool
    steps: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    status_codes: Counter = field(default_factory=Counter)


async def timed(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> tuple[httpx.Response, float]:
    start = time.perf_counter()
    resp = await client.request(method, url, **kwargs)
    ms = (time.perf_counter() - start) * 1000
    return resp, ms


async def login(client: httpx.AsyncClient, base: str, username: str, password: str) -> httpx.Response:
    return (
        await timed(
            client,
            "POST",
            f"{base}/login",
            data={"username": username, "password": password, "next": "/"},
            follow_redirects=False,
        )
    )[0]


async def run_user_session(
    user_id: int,
    base: str,
    role: str,
    username: str,
    password: str,
    batch_ids: list[str],
    iterations: int,
    timeout: float,
) -> UserResult:
    result = UserResult(user_id=user_id, role=role, ok=True)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=False) as client:
        try:
            # Login
            r, ms = await timed(
                client,
                "POST",
                f"{base}/login",
                data={"username": username, "password": password, "next": "/"},
            )
            result.latencies_ms.append(ms)
            result.status_codes[r.status_code] += 1
            if r.status_code not in (200, 303):
                result.ok = False
                result.errors.append(f"login status {r.status_code}")
                return result
            if "session" not in r.cookies and not client.cookies:
                # Starlette may set cookie on response
                pass
            result.steps.append("login")

            for i in range(iterations):
                # Dashboard
                r, ms = await timed(client, "GET", f"{base}/")
                result.latencies_ms.append(ms)
                result.status_codes[r.status_code] += 1
                if r.status_code != 200:
                    result.ok = False
                    result.errors.append(f"dashboard {r.status_code}")
                    break
                result.steps.append("dashboard")

                # Health (public)
                r, ms = await timed(client, "GET", f"{base}/health")
                result.latencies_ms.append(ms)
                result.status_codes[r.status_code] += 1
                if r.status_code != 200:
                    result.ok = False
                    result.errors.append(f"health {r.status_code}")

                # Ready
                r, ms = await timed(client, "GET", f"{base}/ready")
                result.latencies_ms.append(ms)
                result.status_codes[r.status_code] += 1
                if r.status_code != 200:
                    result.ok = False
                    result.errors.append(f"ready {r.status_code}")

                if not batch_ids:
                    continue

                batch_id = batch_ids[user_id % len(batch_ids)]
                form_type = FORM_TYPES[(user_id + i) % len(FORM_TYPES)]

                # Batch detail
                r, ms = await timed(client, "GET", f"{base}/batches/{batch_id}")
                result.latencies_ms.append(ms)
                result.status_codes[r.status_code] += 1
                if r.status_code not in (200, 303, 404):
                    result.ok = False
                    result.errors.append(f"batch detail {r.status_code}")
                else:
                    result.steps.append("batch_detail")

                # Form page
                r, ms = await timed(client, "GET", f"{base}/batches/{batch_id}/forms/{form_type}")
                result.latencies_ms.append(ms)
                result.status_codes[r.status_code] += 1
                if r.status_code not in (200, 303, 403, 404):
                    result.ok = False
                    result.errors.append(f"form page {r.status_code}")
                else:
                    result.steps.append(f"form:{form_type}")

                # Accrual API write (best-effort — may fail if locked / wrong form type)
                if form_type not in ("daily_production", "pick_list"):
                    payload = {
                        "operator_identifier": f"load-u{user_id}",
                        "payload": {
                            "note": f"concurrent load {user_id}-{i}-{uuid.uuid4().hex[:6]}",
                        },
                    }
                    r, ms = await timed(
                        client,
                        "POST",
                        f"{base}/api/batches/{batch_id}/forms/{form_type}/readings",
                        json=payload,
                    )
                    result.latencies_ms.append(ms)
                    result.status_codes[r.status_code] += 1
                    # 200/201 success; 403/409/422 acceptable under lock/validation
                    if r.status_code >= 500:
                        result.ok = False
                        result.errors.append(f"reading POST 5xx {r.status_code}")
                    else:
                        result.steps.append(f"reading:{r.status_code}")

                # Manager-only endpoints: operators should be blocked cleanly
                if role == "operator":
                    r, ms = await timed(client, "GET", f"{base}/batches/new")
                    result.latencies_ms.append(ms)
                    result.status_codes[r.status_code] += 1
                    if r.status_code not in (303, 403, 401):
                        # 200 would be authz failure
                        if r.status_code == 200:
                            result.ok = False
                            result.errors.append("operator accessed /batches/new")
                    result.steps.append(f"op_new_run:{r.status_code}")

        except Exception as exc:  # noqa: BLE001 — capture for load report
            result.ok = False
            result.errors.append(f"exception: {type(exc).__name__}: {exc}")

    return result


async def discover_batch_ids(base: str, username: str, password: str) -> list[str]:
    """Login as manager and scrape batch UUIDs from the dashboard HTML."""
    import re

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await client.post(
            f"{base}/login",
            data={"username": username, "password": password, "next": "/"},
        )
        r = await client.get(f"{base}/")
        if r.status_code != 200:
            return []
        ids = re.findall(
            r"/batches/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            r.text,
            flags=re.I,
        )
        # unique preserve order
        seen: set[str] = set()
        out: list[str] = []
        for i in ids:
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out


async def main_async(args: argparse.Namespace) -> int:
    base = args.base_url.rstrip("/")
    users = args.users

    print(f"Target: {base}")
    print(f"Users:  {users} concurrent sessions ({args.iterations} iteration(s) each)")

    # Preflight
    async with httpx.AsyncClient(timeout=10.0) as client:
        health = await client.get(f"{base}/health")
        ready = await client.get(f"{base}/ready")
        print(f"Preflight health={health.status_code} body={health.text[:80]}")
        print(f"Preflight ready={ready.status_code} body={ready.text[:120]}")
        if health.status_code != 200 or ready.status_code != 200:
            print("ABORT: app not healthy/ready")
            return 2

    batch_ids = await discover_batch_ids(base, args.manager_user, args.manager_pass)
    print(f"Discovered {len(batch_ids)} batch id(s) for load paths")

    # Mix: ~70% operators, 30% managers (shared credentials — separate sessions)
    tasks = []
    for i in range(users):
        if i % 10 < 7:
            role, user, pw = "operator", args.operator_user, args.operator_pass
        else:
            role, user, pw = "manager", args.manager_user, args.manager_pass
        tasks.append(
            run_user_session(
                user_id=i,
                base=base,
                role=role,
                username=user,
                password=pw,
                batch_ids=batch_ids,
                iterations=args.iterations,
                timeout=args.timeout,
            )
        )

    t0 = time.perf_counter()
    results: list[UserResult] = await asyncio.gather(*tasks)
    wall = time.perf_counter() - t0

    ok_users = sum(1 for r in results if r.ok)
    fail_users = users - ok_users
    all_lat = [ms for r in results for ms in r.latencies_ms]
    all_codes: Counter = Counter()
    for r in results:
        all_codes.update(r.status_codes)

    print("\n========== MULTI-USER LOAD REPORT ==========")
    print(f"Wall clock:           {wall:.2f}s")
    print(f"Sessions OK / fail:   {ok_users} / {fail_users}")
    print(f"Total HTTP samples:   {len(all_lat)}")
    if all_lat:
        print(f"Latency ms  p50:      {statistics.median(all_lat):.1f}")
        print(f"Latency ms  mean:     {statistics.mean(all_lat):.1f}")
        print(f"Latency ms  p95:      {percentile(all_lat, 95):.1f}")
        print(f"Latency ms  max:      {max(all_lat):.1f}")
    print(f"Status codes:         {dict(all_codes)}")

    # Server still up?
    async with httpx.AsyncClient(timeout=10.0) as client:
        health = await client.get(f"{base}/health")
        ready = await client.get(f"{base}/ready")
        print(f"Postflight health={health.status_code} ready={ready.status_code}")

    if fail_users:
        print("\n--- Failed sessions (sample) ---")
        for r in results:
            if not r.ok:
                print(f"  user={r.user_id} role={r.role} errors={r.errors[:3]} steps={r.steps[-5:]}")

    # Pass criteria: app survives, >=95% sessions OK, no 5xx flood, health ok after
    server_5xx = sum(c for code, c in all_codes.items() if code >= 500)
    post_ok = health.status_code == 200 and ready.status_code == 200
    pass_rate = ok_users / users if users else 0

    print("\n--- Exit criteria ---")
    print(f"  pass_rate >= 0.95:     {pass_rate:.2%}  ({'PASS' if pass_rate >= 0.95 else 'FAIL'})")
    print(f"  5xx count == 0:        {server_5xx}  ({'PASS' if server_5xx == 0 else 'FAIL'})")
    print(f"  postflight healthy:    {'PASS' if post_ok else 'FAIL'}")
    print(f"  users >= 20:           {users}  ({'PASS' if users >= 20 else 'FAIL'})")

    if pass_rate >= 0.95 and server_5xx == 0 and post_ok and users >= 20:
        print("\nOVERALL: PASS")
        return 0
    print("\nOVERALL: FAIL")
    return 1


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Berton multi-user concurrent load test")
    p.add_argument("--base-url", default=DEFAULT_BASE)
    p.add_argument("--users", type=int, default=20)
    p.add_argument("--iterations", type=int, default=2)
    p.add_argument("--timeout", type=float, default=30.0)
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
