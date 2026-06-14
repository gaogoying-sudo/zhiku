#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def main() -> int:
    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[3]
    backend_dir = script_path.parents[1]
    load_env_file(repo_root / "deploy" / ".env")
    if (not os.environ.get("CACHE_DIR") or os.environ.get("CACHE_DIR", "").startswith("/app/")) and not Path("/app").exists():
        os.environ["CACHE_DIR"] = str(repo_root / "output" / "local_cache")
    if (not os.environ.get("OIL_THERMAL_DATA_DIR") or os.environ.get("OIL_THERMAL_DATA_DIR", "").startswith("/app/")) and not Path("/app").exists():
        os.environ["OIL_THERMAL_DATA_DIR"] = str(repo_root / "deploy" / "data")
    os.environ.setdefault("LOG_RECONCILIATION_OUTPUT_DIR", str(repo_root / "output"))
    sys.path.insert(0, str(backend_dir))

    import main as zhiku_main

    parser = argparse.ArgumentParser(description="Reconcile one Zhiku log package across raw logs, parser artifacts, structured DB, and page summaries.")
    parser.add_argument("--file-id", required=True, type=int, help="machine_ftp/device_log_packages file id")
    parser.add_argument("--refresh", action="store_true", help="force log download/unzip/parser refresh instead of reusing caches")
    parser.add_argument("--no-write-report", action="store_true", help="do not write output/log_reconciliation_<file_id> reports")
    parser.add_argument("--pretty", action="store_true", help="print full pretty JSON instead of compact summary")
    args = parser.parse_args()

    payload = zhiku_main.build_log_reconciliation(
        args.file_id,
        write_report=not args.no_write_report,
        refresh=args.refresh,
    )
    if args.pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        summary = {
            "file_id": payload.get("file_id"),
            "sn": payload.get("sn"),
            "file_name": payload.get("file_name"),
            "difference_count": len(payload.get("differences") or []),
            "differences": payload.get("differences") or [],
            "report_json_path": (payload.get("export_summary") or {}).get("report_json_path"),
            "report_markdown_path": (payload.get("export_summary") or {}).get("report_markdown_path"),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
