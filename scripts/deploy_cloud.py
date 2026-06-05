#!/usr/bin/env python3
"""Upload deploy/ to the cloud host and rebuild docker compose.

Secrets are read locally from handover/01-SECRETS-AND-ACCOUNTS.md and never
printed. This script is intentionally boring so AI agents and humans can run the
same deployment path without retyping SSH commands.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECRETS_FILE = ROOT / "handover" / "01-SECRETS-AND-ACCOUNTS.md"


def read_secret(label: str) -> str:
    text = SECRETS_FILE.read_text(encoding="utf-8")
    pattern = rf"{re.escape(label)}\s*\|\s*`([^`]+)`"
    match = re.search(pattern, text)
    if not match:
        raise SystemExit(f"Missing secret label: {label}")
    return match.group(1)


def redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def run_pexpect(cmd: str, password: str, cwd: Path | None = None, timeout: int = 300) -> str:
    try:
        import pexpect
    except ImportError as exc:
        raise SystemExit("pexpect is required. Install with: python3 -m pip install pexpect") from exc

    child = pexpect.spawn("/bin/zsh", ["-lc", cmd], cwd=str(cwd or ROOT), encoding="utf-8", timeout=timeout)
    chunks: list[str] = []
    while True:
        idx = child.expect(
            [
                r"password for [^:]+:",
                r"\[sudo\] password for [^:]+:",
                r"password:",
                r"Permission denied",
                pexpect.EOF,
                pexpect.TIMEOUT,
            ]
        )
        chunks.append(child.before or "")
        if idx in (0, 1, 2):
            child.sendline(password)
        elif idx == 3:
            raise SystemExit("Permission denied while connecting to cloud host")
        elif idx == 4:
            break
        else:
            raise SystemExit(f"Command timed out: {cmd}")
    return redact("".join(chunks), [password])


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy Zhiku dashboard to cloud")
    parser.add_argument("--skip-check", action="store_true", help="skip scripts/check_project.sh")
    parser.add_argument("--skip-build", action="store_true", help="upload only; do not rebuild containers")
    args = parser.parse_args()

    host = read_secret("IP")
    user = read_secret("SSH 用户")
    password = read_secret("SSH 密码")
    target = "/opt/zhiku-dashboard"

    if not args.skip_check:
        subprocess.run([str(ROOT / "scripts" / "check_project.sh")], cwd=ROOT, check=True)

    upload_cmd = (
        "COPYFILE_DISABLE=1 tar "
        "--exclude='api_cache' --exclude='db_data' --exclude='._*' "
        "--exclude='.DS_Store' --exclude='__pycache__' "
        "-czf - . | "
        f"ssh -o StrictHostKeyChecking=no {user}@{host} "
        f"'mkdir -p {target} && tar --no-same-owner --warning=no-unknown-keyword -xzf - -C {target}'"
    )
    print("==> Upload deploy/ to cloud")
    print(run_pexpect(upload_cmd, password, cwd=ROOT / "deploy", timeout=240)[-3000:])

    if args.skip_build:
        print("OK: upload complete; build skipped")
        return 0

    build_cmd = (
        f"ssh -tt -o StrictHostKeyChecking=no {user}@{host} "
        f"'cd {target} && sudo -S docker compose up -d --force-recreate --build'"
    )
    print("==> Rebuild cloud containers")
    print(run_pexpect(build_cmd, password, cwd=ROOT, timeout=360)[-5000:])
    print("OK: cloud deploy complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
