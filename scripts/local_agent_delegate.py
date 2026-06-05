#!/usr/bin/env python3
"""Delegate low-risk mechanical work to a local Ollama model.

This script is intentionally constrained. It can run only a small allowlist of
project automation commands, then asks a local model to summarize the result.
Use Codex for architecture, code changes, data correctness, and final judgment.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("LOCAL_AGENT_MODEL", "qwen2.5:3b")
MAX_OUTPUT_CHARS = int(os.environ.get("LOCAL_AGENT_MAX_OUTPUT", "12000"))

SAFE_COMMANDS = {
    "check": ["make", "check"],
    "smoke": ["make", "smoke"],
    "status": ["make", "status"],
}

DEPLOY_COMMANDS = {
    "deploy": ["make", "deploy"],
    "release": ["make", "release"],
}


def ollama_generate(model: str, prompt: str) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 8192,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(f"Cannot reach Ollama at {OLLAMA_URL}: {exc}") from exc
    return str(body.get("response") or "").strip()


def run_command(command_key: str, allow_deploy: bool, smoke_keyword: str, smoke_sn: str) -> tuple[int, str, str]:
    commands = dict(SAFE_COMMANDS)
    if allow_deploy:
        commands.update(DEPLOY_COMMANDS)
    if command_key not in commands:
        allowed = ", ".join(sorted(commands))
        raise SystemExit(f"Command '{command_key}' is not allowed. Allowed: {allowed}")

    env = os.environ.copy()
    if command_key in {"smoke", "release"}:
        if smoke_keyword:
            env["SMOKE_KEYWORD"] = smoke_keyword
        if smoke_sn:
            env["SMOKE_SN"] = smoke_sn

    cmd = commands[command_key]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=900 if command_key in {"deploy", "release"} else 180,
    )
    output = proc.stdout[-MAX_OUTPUT_CHARS:]
    return proc.returncode, shlex.join(cmd), output


def build_prompt(task: str, mode: str, command: str | None, code: int | None, output: str | None) -> str:
    parts = [
        "你是智库项目的本地小模型助手，只负责低风险机械工作总结。",
        "不要提出大改代码方案，不要假装已经部署，不要输出任何密码、token 或数据库连接。",
        "请用简洁中文输出：结论、关键证据、风险/下一步。",
        f"任务：{task or '-'}",
        f"模式：{mode}",
    ]
    if command is not None:
        parts.append(f"命令：{command}")
    if code is not None:
        parts.append(f"退出码：{code}")
    if output:
        parts.append("命令输出如下：\n```text\n" + output + "\n```")
    return "\n\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Use local Ollama model for low-risk delegation")
    parser.add_argument("--mode", choices=["plan", "run", "summarize"], default="summarize")
    parser.add_argument("--task", default="", help="task description for the local model")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--command", choices=sorted(set(SAFE_COMMANDS) | set(DEPLOY_COMMANDS)), help="allowed command key")
    parser.add_argument("--allow-deploy", action="store_true", help="allow deploy/release command keys")
    parser.add_argument("--smoke-keyword", default=os.environ.get("SMOKE_KEYWORD", "appVersion"))
    parser.add_argument("--smoke-sn", default=os.environ.get("SMOKE_SN", ""))
    parser.add_argument("--input-file", help="optional file whose content should be summarized")
    args = parser.parse_args()

    output = ""
    code = None
    command_text = None

    if args.mode == "run":
        if not args.command:
            raise SystemExit("--command is required in run mode")
        code, command_text, output = run_command(args.command, args.allow_deploy, args.smoke_keyword, args.smoke_sn)
    elif args.input_file:
        output = Path(args.input_file).read_text(encoding="utf-8")[-MAX_OUTPUT_CHARS:]
    else:
        output = sys.stdin.read()[-MAX_OUTPUT_CHARS:] if not sys.stdin.isatty() else ""

    prompt = build_prompt(args.task, args.mode, command_text, code, output)
    response = ollama_generate(args.model, prompt)
    print(response)
    if code is not None:
        return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
