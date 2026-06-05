#!/usr/bin/env python3
"""Show remote docker compose status and recent API logs without exposing secrets."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECRETS_FILE = ROOT / "handover" / "01-SECRETS-AND-ACCOUNTS.md"


def read_secret(label: str) -> str:
    text = SECRETS_FILE.read_text(encoding="utf-8")
    match = re.search(rf"{re.escape(label)}\s*\|\s*`([^`]+)`", text)
    if not match:
        raise SystemExit(f"Missing secret label: {label}")
    return match.group(1)


def run_pexpect(cmd: str, password: str, timeout: int = 120) -> str:
    import pexpect

    child = pexpect.spawn("/bin/zsh", ["-lc", cmd], cwd=str(ROOT), encoding="utf-8", timeout=timeout)
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
            raise SystemExit("Permission denied")
        elif idx == 4:
            break
        else:
            raise SystemExit("cloud status timeout")
    text = "".join(chunks).replace(password, "[REDACTED]")
    text = re.sub(r"token=[A-Za-z0-9._~+/=-]+", "token=[REDACTED]", text)
    return text


def main() -> int:
    host = read_secret("IP")
    user = read_secret("SSH 用户")
    password = read_secret("SSH 密码")
    cmd = (
        f"ssh -o StrictHostKeyChecking=no {user}@{host} "
        "'cd /opt/zhiku-dashboard && sudo -S docker compose ps && sudo -S docker compose logs --tail=40 api'"
    )
    print(run_pexpect(cmd, password)[-6000:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
