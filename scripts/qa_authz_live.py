"""
Live authorization boundary checks (TEST_PLAN §2.11) against a running instance.

Operator must not reach manager-only HTML/API; manager can. Shared-login sessions
are independent cookies.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx

DEFAULT_BASE = "http://127.0.0.1:8001"


async def session_client(base: str, username: str, password: str) -> httpx.AsyncClient:
    client = httpx.AsyncClient(timeout=20.0, follow_redirects=False)
    r = await client.post(
        f"{base}/login",
        data={"username": username, "password": password, "next": "/"},
    )
    if r.status_code not in (200, 303):
        await client.aclose()
        raise RuntimeError(f"login failed for {username}: {r.status_code}")
    return client


async def main_async(args: argparse.Namespace) -> int:
    base = args.base_url.rstrip("/")
    failures: list[str] = []
    checks = 0

    async def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal checks
        checks += 1
        status = "PASS" if cond else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
        if not cond:
            failures.append(name)

    op = await session_client(base, args.operator_user, args.operator_pass)
    mgr = await session_client(base, args.manager_user, args.manager_pass)
    try:
        print("=== Authz matrix (live) ===")

        r = await op.get(f"{base}/")
        await check("operator dashboard 200", r.status_code == 200, str(r.status_code))

        r = await op.get(f"{base}/batches/new")
        await check(
            "operator cannot open new run (redirect/403)",
            r.status_code in (303, 401, 403),
            str(r.status_code),
        )

        r = await mgr.get(f"{base}/batches/new")
        await check("manager can open new run", r.status_code == 200, str(r.status_code))

        # Unauthenticated API
        async with httpx.AsyncClient(timeout=15.0) as anon:
            r = await anon.get(f"{base}/api/batches")
            await check(
                "anon API batches blocked",
                r.status_code in (401, 403, 303, 404, 405),
                str(r.status_code),
            )

            r = await anon.get(f"{base}/health")
            await check("anon health allowed", r.status_code == 200, str(r.status_code))

        # Operator POST compile path (need a batch id if any)
        import re

        r = await mgr.get(f"{base}/", follow_redirects=True)
        ids = re.findall(
            r"/batches/([0-9a-fA-F-]{36})",
            r.text,
        )
        if ids:
            bid = ids[0]
            r = await op.post(f"{base}/batches/{bid}/compile")
            await check(
                "operator compile blocked",
                r.status_code in (303, 401, 403, 405, 422),
                str(r.status_code),
            )
            r = await op.post(f"{base}/batches/{bid}/reopen")
            await check(
                "operator reopen blocked",
                r.status_code in (303, 401, 403, 405, 422),
                str(r.status_code),
            )
        else:
            print("  [SKIP] no batches for compile/reopen checks")

    finally:
        await op.aclose()
        await mgr.aclose()

    print(f"\nChecks: {checks}  Failures: {len(failures)}")
    if failures:
        print("FAILED:", ", ".join(failures))
        return 1
    print("OVERALL: PASS")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=DEFAULT_BASE)
    p.add_argument("--manager-user", default="manager")
    p.add_argument("--manager-pass", default="manager")
    p.add_argument("--operator-user", default="operator")
    p.add_argument("--operator-pass", default="operator")
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(parse_args())))
