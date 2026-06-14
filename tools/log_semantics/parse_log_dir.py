#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deploy.backend.log_semantics.exporters import export_result
from deploy.backend.log_semantics.parser import parse_log_directory


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse an extracted device log directory into versioned semantic artifacts.")
    parser.add_argument("--input", required=True, help="Extracted log directory")
    parser.add_argument("--output", required=True, help="Artifact output directory")
    parser.add_argument("--default-year", type=int, help="Year for timestamps such as [06-12 09:31:19]")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--debug-commands", action="store_true", help="Also write high-volume command_events.jsonl")
    args = parser.parse_args()
    result = parse_log_directory(args.input, args.default_year, args.timezone, args.debug_commands)
    output = export_result(result, args.output, args.debug_commands)
    print(f"parsed {len(result.android_events)} android events, {len(result.temperature_samples)} temperature samples")
    print(f"created {len(result.sessions)} sessions; artifacts: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
