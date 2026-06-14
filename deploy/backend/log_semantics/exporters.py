from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from . import LOG_SEMANTICS_VERSION, SCHEMA_VERSION
from .models import ParseResult


def _json_default(value: Any) -> str:
    return str(value)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")


def write_csv(path: Path, rows: List[Dict[str, Any]], fallback_fields: List[str]) -> None:
    fields = list(fallback_fields)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def export_result(result: ParseResult, output_dir: str, include_command_events: bool = False) -> Path:
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "summary.json", result.summary)
    write_json(output / "file_inventory.json", result.file_inventory)
    datasets = {
        "android_events": result.android_events, "temperature_samples": result.temperature_samples,
        "power_events": result.power_events, "action_events": result.action_events,
        "internal_sessions": result.sessions, "unified_timeline": result.timeline,
    }
    for name, rows in datasets.items():
        write_jsonl(output / f"{name}.jsonl", rows)
        write_csv(output / f"{name}.csv", rows, ["timestamp", "event_type", "source_file", "line_no", "raw_line"])
    if include_command_events:
        write_jsonl(output / "command_events.jsonl", result.command_events)
    write_csv(output / "unknown_patterns.csv", result.unknown_patterns, [
        "source_file", "line_no", "timestamp", "raw_line", "guessed_category", "reason", "suggested_parser_rule"
    ])
    write_json(output / "integration_payload.json", _integration_payload(result))
    (output / "evidence_report.md").write_text(_evidence_report(result), encoding="utf-8")
    return output


def _integration_payload(result: ParseResult) -> Dict[str, Any]:
    return {
        "parser_version": LOG_SEMANTICS_VERSION, "schema_version": SCHEMA_VERSION,
        "source": {"input_dir": result.input_dir, "source_files": result.summary["source_files"]},
        "file_inventory": result.file_inventory, "sessions": result.sessions,
        "temperature_samples": result.temperature_samples, "power_events": result.power_events,
        "action_events": result.action_events, "timeline": result.timeline,
        "unknown_patterns": result.unknown_patterns, "summary": result.summary,
        "integration_hints": {
            "target_tables": {
                "cook_jobs": ["sessions"], "cook_temperature_samples": ["temperature_samples"],
                "cook_power_events": ["power_events"], "cook_action_events": ["action_events"],
                "log_internal_sessions": ["sessions"],
            }
        },
    }


def _evidence_report(result: ParseResult) -> str:
    summary = result.summary
    lines = [
        "# Device Log Semantics Evidence Report", "",
        f"- Parser: `{LOG_SEMANTICS_VERSION}` / `{SCHEMA_VERSION}`",
        f"- Input: `{result.input_dir}`",
        f"- Time range: {summary['time_range']['start']} to {summary['time_range']['end']}",
        f"- Sessions: {len(result.sessions)}",
        f"- Unknown patterns: {len(result.unknown_patterns)}", "",
        "## File Inventory", "",
    ]
    lines.extend(f"- `{item['file_type']}` `{item['source_file']}` ({item['size_bytes']} bytes)" for item in result.file_inventory["files"])
    lines.extend(["", "## Thermal And Power Maxima", ""])
    lines.extend([
        f"- Max filtered temperature: {summary['thermal_summary']['max_filtered_temp_c']}",
        f"- Max infrared temperature: {summary['thermal_summary']['max_infrared_temp_c']}",
        f"- Max output temperature: {summary['thermal_summary']['max_output_temp_c']}",
        f"- Max command power: {summary['power_summary']['max_command_power_kw']} kW",
        f"- Max actual power: {summary['power_summary']['max_actual_power_kw']} kW",
    ])
    lines.extend(["", "## Sessions", ""])
    for session in result.sessions:
        lines.extend([
            f"### {session['session_id']} ({session['session_type']})", "",
            f"- Range: {session['start_time']} to {session['end_time']} ({session['duration_seconds']}s)",
            f"- Recipe: {session.get('recipe_name') or '-'} / {session.get('recipe_id') or '-'}",
            f"- Start evidence: `{session['start_evidence']}`",
            f"- End evidence: `{session['end_evidence']}`",
            f"- Max output temperature: {session['max_output_temp_c']}",
            f"- Max command/actual power: {session['max_command_power_kw']} / {session['max_actual_power_kw']} kW",
            f"- Actions liquid/lean/roll/weigh: {session['liquid_feed_count']}/{session['lean_event_count']}/{session['roll_event_count']}/{session['weigh_event_count']}",
            f"- Candidate risk tags: {', '.join(session['risk_tags']) or '-'}", "",
        ])
    lines.extend(["## Unknown Pattern Summary", ""])
    for item in result.unknown_patterns[:20]:
        lines.append(f"- `{item['source_file']}:{item['line_no']}` {item['guessed_category']}: `{item['raw_line']}`")
    lines.extend([
        "", "## Uncertain Semantics", "",
        "- `temp_limit_c` is derived from the raw value divided by 10 and requires embedded-system confirmation.",
        "- Candidate risk tags are screening signals, not accident conclusions.",
        "- Android output temperature and high-frequency temperature output are retained as separate measurements.",
    ])
    return "\n".join(lines) + "\n"
