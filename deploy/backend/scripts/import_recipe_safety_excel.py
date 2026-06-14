#!/usr/bin/env python3
"""Import recipe safety Excel into local zhiku-mysql and export cleaned workbook."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DEPLOY_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Import recipe safety Excel")
    parser.add_argument("--file", required=True, help="source .xlsx path")
    parser.add_argument("--batch-name", default="", help="optional batch code")
    parser.add_argument("--output", default="", help="cleaned workbook path")
    parser.add_argument("--dry-run", action="store_true", help="parse and report without DB writes")
    parser.add_argument("--force", action="store_true", help="allow importing same file hash as a new batch")
    args = parser.parse_args()

    load_env_file(PROJECT_DEPLOY_DIR / ".env")

    from recipe_safety import parse_workbook, write_cleaned_workbook
    from main import persist_recipe_safety_analysis

    source = Path(args.file).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"Source file does not exist: {source}")
    output = Path(args.output or (PROJECT_DEPLOY_DIR / "output" / f"recipe_safety_cleaned_{source.stem}.xlsx")).expanduser().resolve()

    analysis = parse_workbook(source, batch_code=args.batch_name, imported_by="script")
    persisted = persist_recipe_safety_analysis(analysis, force=args.force, dry_run=args.dry_run, output_path=str(output))
    if not args.dry_run:
        write_cleaned_workbook(source, analysis, output)
    print({
        "batch_id": persisted.get("batch_id"),
        "dry_run": args.dry_run,
        "output": str(output),
        "overview": analysis.get("overview"),
        "counts": persisted,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
