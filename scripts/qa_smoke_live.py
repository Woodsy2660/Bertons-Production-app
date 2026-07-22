"""Post-build / live smoke (TEST_PLAN §2.4)."""

from __future__ import annotations

import argparse
import sys
import time

import httpx

DEFAULT_BASE = "http://127.0.0.1:8001"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=DEFAULT_BASE)
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    t0 = time.perf_counter()
    fails: list[str] = []

    with httpx.Client(timeout=15.0, follow_redirects=False) as c:
        for path, ok in [("/health", {200}), ("/ready", {200})]:
            r = c.get(f"{base}{path}")
            print(f"  {path} -> {r.status_code} {r.text[:100]}")
            if r.status_code not in ok:
                fails.append(path)

        r = c.get(f"{base}/login")
        print(f"  /login -> {r.status_code}")
        if r.status_code != 200:
            fails.append("/login")

        r = c.post(
            f"{base}/login",
            data={"username": "manager", "password": "manager", "next": "/"},
        )
        print(f"  POST /login -> {r.status_code}")
        if r.status_code not in (200, 303):
            fails.append("POST /login")

        # session cookie jar
        r = c.get(f"{base}/", follow_redirects=True)
        print(f"  GET / (auth) -> {r.status_code} len={len(r.text)}")
        if r.status_code != 200:
            fails.append("dashboard")

    elapsed = time.perf_counter() - t0
    print(f"Smoke elapsed: {elapsed:.2f}s")
    if fails:
        print("FAIL:", fails)
        return 1
    if elapsed > 60:
        print("WARN: smoke exceeded 60s budget")
    print("SMOKE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
