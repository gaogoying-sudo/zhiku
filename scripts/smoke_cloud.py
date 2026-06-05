#!/usr/bin/env python3
"""Cloud smoke checks for the Zhiku dashboard."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
SECRETS_FILE = ROOT / "handover" / "01-SECRETS-AND-ACCOUNTS.md"


def read_secret(label: str) -> str:
    text = SECRETS_FILE.read_text(encoding="utf-8")
    match = re.search(rf"{re.escape(label)}\s*\|\s*`([^`]+)`", text)
    if not match:
        raise SystemExit(f"Missing secret label: {label}")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test cloud deployment")
    parser.add_argument("--keyword", action="append", default=[], help="frontend keyword that must exist")
    parser.add_argument("--sn", default="", help="optional device SN to verify lightweight /api/devices/search")
    parser.add_argument("--full-device", action="store_true", help="verify full /api/search/{sn}; can be slow for large devices")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    base = read_secret("Web 地址").rstrip("/")
    admin_password = read_secret("Admin 密码 / Token")

    session = requests.Session()
    frontend = session.get(base, timeout=args.timeout)
    frontend.encoding = "utf-8"
    html = frontend.text
    print(f"frontend: {len(html)} bytes")

    keywords = args.keyword or ["appVersion"]
    missing = [kw for kw in keywords if kw not in html]
    if missing:
        print(f"ERROR: missing frontend keyword(s): {', '.join(missing)}", file=sys.stderr)
        return 1
    print(f"frontend keywords OK: {', '.join(keywords)}")

    login = session.post(
        f"{base}/api/login",
        json={"username": "admin", "password": admin_password},
        timeout=args.timeout,
    )
    print(f"login: {login.status_code}")
    if login.status_code != 200:
        return 1

    if args.sn:
        token = login.json()["token"]
        if args.full_device:
            device = session.get(
                f"{base}/api/search/{args.sn}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=max(args.timeout, 60),
            )
            print(f"full device {args.sn}: {device.status_code}")
            if device.status_code != 200:
                print(device.text[:500], file=sys.stderr)
                return 1
            payload = device.json()
            print(
                "full device summary:",
                f"logs={payload.get('stats', {}).get('total_logs')}",
                f"recipes={payload.get('stats', {}).get('recipe_count')}",
                f"log_files={len(payload.get('device_logs') or [])}",
            )
            return 0
        lookup = session.get(
            f"{base}/api/devices/search",
            params={"keyword": args.sn, "limit": 1},
            headers={"Authorization": f"Bearer {token}"},
            timeout=args.timeout,
        )
        print(f"device lookup {args.sn}: {lookup.status_code}")
        if lookup.status_code != 200:
            print(lookup.text[:500], file=sys.stderr)
            return 1
        payload = lookup.json()
        print(f"device lookup results: {payload.get('total')}")

    print("OK: cloud smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
