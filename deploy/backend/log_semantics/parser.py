from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from . import LOG_SEMANTICS_VERSION, SCHEMA_VERSION
from .models import LogRecord, ParseResult
from .patterns import *
from .sessionizer import build_sessions
from .timeline import build_timeline

POWER_TYPES = {"command_power_set", "command_power_result", "power_feedback"}
ACTION_TYPES = {
    "lean_start", "lean_success", "lean_data_collect", "roll_start", "roll_success",
    "roll_data_collect", "liquid_feed_start", "liquid_feed_success", "liquid_consumed",
    "liquid_capacity_update", "weigh_start", "weigh_success", "weigh_result",
    "speech_start", "speech_complete", "data_collect", "protect_pot_marker",
    "recipe_recording", "fan_start",
}


def _read_lines(path: Path) -> Iterable[Tuple[int, str]]:
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            yield line_no, line.replace("\x00", "").rstrip("\r\n")


def _infer_year(path: Path) -> Optional[int]:
    match = re.search(r"(20\d{2})[_-]?\d{2}[_-]?\d{2}", path.name)
    return int(match.group(1)) if match else None


def parse_timestamp(line: str, default_year: Optional[int], path: Path) -> Tuple[Optional[str], Optional[str], str, Optional[str]]:
    match = TIMESTAMP_RE.match(line)
    if not match:
        return None, None, line.strip(), None
    raw = match.group("ts")
    normalized = raw.replace("_", " ")
    warning = None
    try:
        if re.match(r"^\d{2}-\d{2}", normalized):
            year = default_year or _infer_year(path)
            if year is None:
                return None, raw, line[match.end():], f"missing year for {path.name}"
            normalized = f"{year}-{normalized}"
        parsed = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
        return parsed.strftime("%Y-%m-%d %H:%M:%S"), raw, line[match.end():].strip(), warning
    except ValueError:
        return None, raw, line[match.end():].strip(), f"invalid timestamp {raw!r} in {path.name}"


def _record(path: Path, line_no: int, raw_line: str, timestamp: Optional[str], raw_timestamp: Optional[str],
            event_type: str, fields: Optional[Dict[str, Any]] = None, confidence: float = 1.0,
            risk_tags: Optional[List[str]] = None) -> Dict[str, Any]:
    return LogRecord(
        source_file=str(path), line_no=line_no, raw_line=raw_line, timestamp=timestamp,
        raw_timestamp=raw_timestamp, event_type=event_type, confidence=confidence,
        fields=fields or {}, risk_tags=risk_tags or [],
    ).to_dict()


def _power_fields(command: Optional[int] = None, actual: Optional[int] = None) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    if command is not None:
        fields.update(command_power_w=command, command_power_kw=command / 1000.0)
    if actual is not None:
        fields.update(actual_power_w=actual, actual_power_kw=actual / 1000.0)
    return fields


def parse_android_file(path: Path, default_year: Optional[int]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str], Dict[str, int]]:
    events: List[Dict[str, Any]] = []
    unknown: List[Dict[str, Any]] = []
    warnings: List[str] = []
    command_counts = {key: 0 for key in COMMAND_PATTERNS}
    last_timestamp = last_raw_timestamp = None

    for line_no, raw_line in _read_lines(path):
        if not raw_line.strip():
            continue
        timestamp, raw_timestamp, body, warning = parse_timestamp(raw_line, default_year, path)
        if warning and warning not in warnings:
            warnings.append(warning)
        if timestamp:
            last_timestamp, last_raw_timestamp = timestamp, raw_timestamp
        else:
            timestamp, raw_timestamp = last_timestamp, last_raw_timestamp

        event_type = None
        fields: Dict[str, Any] = {}
        confidence = 1.0
        match = COOKING_START_RE.search(body)
        if match:
            event_type, fields = "cooking_start", {"recipe_name": match.group("name").strip(), "recipe_id": match.group("id")}
        else:
            for key, pattern in VERSION_PATTERNS.items():
                match = pattern.search(body)
                if match:
                    event_type, fields = key, {key: match.group("value")}
                    break
        if not event_type and (match := NETWORK_RE.search(body)):
            parsed = urlsplit(match.group("url"))
            event_type = "network_request"
            fields = {
                "url_domain": parsed.hostname,
                "url_path": parsed.path,
                "raw_url_hash": hashlib.sha256(match.group("url").encode()).hexdigest(),
            }
        elif not event_type and (match := SCENE_RE.search(body)):
            event_type, fields = "scene_change", {"scene_name": match.group("scene")}
        elif not event_type and (match := ACTIVITY_RE.search(body)):
            event_type, fields = "activity_lifecycle", {
                "activity_name": match.group("activity"), "lifecycle_action": f"on{match.group('action')}"
            }
        elif not event_type and ("快速养锅" in body or "Completing pot raising" in body):
            event_type, fields = "protect_pot_marker", {"marker": body}
        elif not event_type and (match := RECORDING_RE.search(body)):
            event_type, fields = "recipe_recording", {"record_time_value": int(match.group("value"))}
        elif not event_type and (match := TEMP_LIMIT_RE.search(body)):
            raw = int(match.group("value"))
            event_type, fields, confidence = "temp_limit_set", {
                "temp_limit_raw": raw, "temp_limit_c": raw / 10.0,
                "result": "success" if match.group("result") == "成功" else match.group("result"),
            }, 0.8
        elif not event_type and (match := POWER_FEEDBACK_RE.search(body)):
            command, actual = int(match.group("command")), int(match.group("actual"))
            fields = _power_fields(command, actual)
            fields.update(
                bus_voltage=float(match.group("bus_voltage")), bus_raw=float(match.group("bus_raw")),
                output_current=float(match.group("current")), frequency=float(match.group("frequency")),
                core_temp_c=float(match.group("core")), coil_temp_c=float(match.group("coil")),
                android_output_temp_c=float(match.group("output")),
            )
            event_type = "power_feedback"
        elif not event_type and (match := POWER_SET_RE.search(body)):
            event_type, fields = "command_power_set", _power_fields(int(match.group("power")))
        elif not event_type and (match := POWER_RESULT_RE.search(body)):
            event_type, fields = "command_power_result", _power_fields(int(match.group("power")))
            fields["result"] = "success" if match.group("result") == "成功" else "failure"
        elif not event_type and "开始检测温度" in body:
            event_type = "temperature_monitor_start"
        elif not event_type and "开始检测输出功率" in body:
            event_type = "power_monitor_start"
        elif not event_type and (match := LEAN_START_RE.search(body)):
            event_type, fields = "lean_start", {"lean_position": match.group("position")}
        elif not event_type and (match := LEAN_SUCCESS_RE.search(body)):
            event_type, fields = "lean_success", {"lean_position": match.group("position"), "result": match.group("result")}
        elif not event_type and (match := ROLL_START_RE.search(body)):
            event_type, fields = "roll_start", {"roll_mode": match.group("mode")}
        elif not event_type and (match := ROLL_SUCCESS_RE.search(body)):
            event_type, fields = "roll_success", {"roll_mode": match.group("mode"), "result": match.group("result")}
        elif not event_type and (match := LIQUID_START_RE.search(body)):
            event_type, fields = "liquid_feed_start", {
                "sauce_name": match.group("name"), "sauce_id": int(match.group("id")),
                "amount_g": float(match.group("amount")), "runtime_ms": int(match.group("runtime")),
            }
        elif not event_type and (match := LIQUID_SUCCESS_RE.search(body)):
            event_type, fields = "liquid_feed_success", {
                "sauce_name": match.group("name"), "amount_g": float(match.group("amount")),
                "runtime_ms": int(match.group("runtime")), "result": match.group("result"),
            }
        elif not event_type and (match := LIQUID_CONSUMED_RE.search(body)):
            event_type, fields = "liquid_consumed", {"sauce_name": match.group("name"), "amount_g": float(match.group("amount"))}
        elif not event_type and (match := LIQUID_CAPACITY_RE.search(body)):
            event_type, fields = "liquid_capacity_update", {"sauce_name": match.group("name"), "remaining_g": float(match.group("remaining"))}
        elif not event_type and (match := WEIGH_START_RE.search(body)):
            event_type, fields = "weigh_start", {"spice_channel": match.group("channel"), "target_weight_g": float(match.group("target"))}
        elif not event_type and (match := WEIGH_SUCCESS_RE.search(body)):
            event_type, fields = "weigh_success", {
                "spice_channel": match.group("channel"), "target_weight_g": float(match.group("target")),
                "result": match.group("result"),
            }
        elif not event_type and (match := WEIGH_RESULT_RE.search(body)):
            event_type, fields = "weigh_result", {
                "spice_channel": match.group("channel"), "target_weight_g": float(match.group("target")),
                "raw_weight": int(match.group("raw")), "origin_weight": int(match.group("origin")),
            }
        elif not event_type and (match := SPEECH_START_RE.search(body)):
            event_type, fields = "speech_start", {"speech_text": match.group("text"), "code": int(match.group("code"))}
        elif not event_type and (match := SPEECH_COMPLETE_RE.search(body)):
            event_type, fields = "speech_complete", {"speech_text": match.group("text")}
        elif not event_type and (match := DATA_COLLECT_RE.search(body)):
            payload = match.group("payload")
            category = next((name for name in ("倾锅", "转锅", "泵", "锅", "机芯", "机器运行") if name in payload), "other")
            if category == "倾锅":
                event_type = "lean_data_collect"
            elif category == "转锅":
                event_type = "roll_data_collect"
            elif "风扇开始工作" in payload:
                event_type = "fan_start"
            else:
                event_type = "data_collect"
            fields = {"collect_category": category, "parsed_payload_json": _parse_key_values(payload)}
            if work_hall := WORK_HALL_RE.search(payload):
                fields.update(work_time_ms=int(work_hall.group("work")), hall=int(work_hall.group("hall")))
        if not event_type:
            for command_type, pattern in COMMAND_PATTERNS.items():
                if pattern.search(body):
                    command_counts[command_type] += 1
                    event_type = command_type
                    confidence = 0.9
                    break
        if not event_type and ERROR_RE.search(body):
            event_type = "mcu_error" if re.search(r"FrameID|heater", body, re.I) else "error"
            fields["error_text"] = body
        if event_type:
            events.append(_record(path, line_no, raw_line, timestamp, raw_timestamp, event_type, fields, confidence, _event_risks(event_type, fields)))
        elif UNKNOWN_KEYWORDS_RE.search(body):
            unknown.append({
                "source_file": str(path), "line_no": line_no, "timestamp": timestamp, "raw_line": raw_line,
                "guessed_category": _guess_category(body), "reason": "keyword-bearing line did not match a stable rule",
                "suggested_parser_rule": "review and add a versioned pattern if semantics are confirmed",
            })
    return events, unknown, warnings, command_counts


def _parse_key_values(payload: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in re.findall(r"([A-Za-z][\w.]*)\s*:\s*([^,]+)", payload):
        value = value.strip()
        try:
            result[key] = float(value) if "." in value else int(value)
        except ValueError:
            result[key] = value
    return result


def _guess_category(body: str) -> str:
    for keyword, category in (
        ("功率", "power"), ("温度", "temperature"), ("液料", "feed"), ("投料", "feed"),
        ("倾锅", "lean"), ("转锅", "roll"), ("称重", "weigh"), ("FrameID", "mcu"),
        ("error", "error"), ("fail", "error"),
    ):
        if keyword.lower() in body.lower():
            return category
    return "unknown"


def _event_risks(event_type: str, fields: Dict[str, Any]) -> List[str]:
    risks: List[str] = []
    command = fields.get("command_power_w")
    actual = fields.get("actual_power_w")
    temp = fields.get("android_output_temp_c")
    if temp is not None:
        for limit in (250, 300, 350):
            if temp > limit:
                risks.append(f"temp_over_{limit}")
    if command is not None:
        if command > 15000:
            risks.append("command_power_over_15kw")
        elif command > 12000:
            risks.append("command_power_over_12kw")
    if actual is not None:
        if actual > 15000:
            risks.append("actual_power_over_15kw")
        elif actual > 12000:
            risks.append("actual_power_over_12kw")
    if event_type == "mcu_error":
        risks.append("no_frame_id" if "FrameID" in fields.get("error_text", "") else "heater_error")
    return risks


def parse_temperature_file(path: Path, default_year: Optional[int]) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    samples: List[Dict[str, Any]] = []
    warnings: List[str] = []
    errors: List[str] = []
    for line_no, raw_line in _read_lines(path):
        if not raw_line.strip():
            continue
        timestamp, raw_timestamp, body, warning = parse_timestamp(raw_line, default_year, path)
        if warning and warning not in warnings:
            warnings.append(warning)
        match = TEMPERATURE_TRIPLET_RE.search(body)
        if not match:
            errors.append(f"{path.name}:{line_no}: invalid temperature sample")
            continue
        values = {key: float(match.group(key)) for key in ("filtered", "infrared", "output")}
        samples.append(_record(path, line_no, raw_line, timestamp, raw_timestamp, "temperature_sample", {
            "filtered_temp_c": values["filtered"], "infrared_temp_c": values["infrared"],
            "output_temp_c": values["output"], "raw_triplet": match.group(0).strip(),
        }, risk_tags=_temperature_risks(values["output"])))
    return samples, warnings, errors


def parse_auxiliary_file(path: Path, default_year: Optional[int], source_type: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    events: List[Dict[str, Any]] = []
    warnings: List[str] = []
    dry_markers = {
        "start dry": "dry_spice_start", "Spice Over": "dry_spice_over",
        "Spice in": "dry_spice_in", "Spice start": "dry_spice_dispense_start",
        "Spice finish put": "dry_spice_dispense_finish",
    }
    for line_no, raw_line in _read_lines(path):
        timestamp, raw_timestamp, body, warning = parse_timestamp(raw_line, default_year, path)
        if warning and warning not in warnings:
            warnings.append(warning)
        event_type = None
        fields: Dict[str, Any] = {"source_type": source_type}
        risks: List[str] = []
        if re.search(r"no FrameID", body, re.I):
            event_type, risks = "mcu_error", ["no_frame_id"]
            fields["error_text"] = body
        elif re.search(r"heaterGetErrCode", body, re.I):
            event_type = "heater_status"
            fields["status_text"] = body
        elif re.search(r"heater.*fail", body, re.I) or (
            re.search(r"heater.*error", body, re.I)
            and not re.search(r"error\s*:\s*(?:0x0+|0)\b", body, re.I)
        ):
            event_type, risks = "mcu_error", ["heater_error"]
            fields["error_text"] = body
        elif source_type == "dryspices":
            event_type = next((kind for marker, kind in dry_markers.items() if marker.lower() in body.lower()), None)
        if event_type:
            event = _record(path, line_no, raw_line, timestamp, raw_timestamp, event_type, fields, 0.9, risks)
            event["source_type"] = source_type
            events.append(event)
    return events, warnings


def _temperature_risks(value: float) -> List[str]:
    return [f"temp_over_{limit}" for limit in (250, 300, 350) if value > limit]


def discover_files(input_dir: Path) -> Dict[str, Any]:
    categories = {
        "android": lambda n: n.startswith("android") and n.endswith(".log"),
        "temperature": lambda n: n.startswith("temperature") and n.endswith(".log"),
        "debug": lambda n: n.startswith("debug") and n.endswith(".log"),
        "main_board": lambda n: n == "main_board.log",
        "dryspices": lambda n: n == "dryspices_board.log",
        "oildrum": lambda n: n == "oildrum_board.log",
    }
    files = sorted(path for path in input_dir.rglob("*") if path.is_file())
    inventory: Dict[str, Any] = {"files": []}
    for category, predicate in categories.items():
        matched = [path for path in files if predicate(path.name.lower())]
        inventory[f"{category}_files"] = [str(path) for path in matched]
        inventory[f"{category}_file_count"] = len(matched)
        inventory["files"].extend({
            "source_file": str(path), "file_type": category, "size_bytes": path.stat().st_size
        } for path in matched)
    return inventory


def parse_log_directory(input_dir: str, default_year: Optional[int] = None,
                        timezone: str = "Asia/Shanghai", debug_commands: bool = False) -> ParseResult:
    root = Path(input_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"input directory does not exist: {root}")
    ZoneInfo(timezone)
    inventory = discover_files(root)
    result = ParseResult(input_dir=str(root), file_inventory=inventory)
    for filename in inventory["android_files"]:
        events, unknown, warnings, counts = parse_android_file(Path(filename), default_year)
        result.android_events.extend(events)
        result.unknown_patterns.extend(unknown)
        result.warnings.extend(w for w in warnings if w not in result.warnings)
        for key, count in counts.items():
            result.command_event_counts[key] = result.command_event_counts.get(key, 0) + count
    for filename in inventory["temperature_files"]:
        samples, warnings, errors = parse_temperature_file(Path(filename), default_year)
        result.temperature_samples.extend(samples)
        result.warnings.extend(w for w in warnings if w not in result.warnings)
        result.parse_errors.extend(errors[:100])
        if len(errors) > 100:
            result.warnings.append(f"{filename}: {len(errors) - 100} additional malformed temperature lines omitted")
    for category in ("debug", "main_board", "dryspices"):
        for filename in inventory[f"{category}_files"]:
            auxiliary, warnings = parse_auxiliary_file(Path(filename), default_year, category)
            result.auxiliary_events.extend(auxiliary)
            result.warnings.extend(w for w in warnings if w not in result.warnings)
    result.command_events = [e for e in result.android_events if e["event_type"] in COMMAND_PATTERNS] if debug_commands else []
    result.android_events = [e for e in result.android_events if e["event_type"] not in COMMAND_PATTERNS]
    result.power_events = [e for e in result.android_events if e["event_type"] in POWER_TYPES]
    result.action_events = [e for e in result.android_events if e["event_type"] in ACTION_TYPES]
    result.sessions = build_sessions(result.android_events, result.temperature_samples)
    result.timeline = build_timeline(result.android_events, result.temperature_samples, result.sessions, result.auxiliary_events)
    result.summary = build_summary(result, timezone)
    return result


def _max(records: List[Dict[str, Any]], key: str) -> Optional[float]:
    values = [record[key] for record in records if record.get(key) is not None]
    return max(values) if values else None


def build_summary(result: ParseResult, timezone: str) -> Dict[str, Any]:
    timestamps = [r["timestamp"] for r in result.android_events + result.temperature_samples if r.get("timestamp")]
    risk_tags = {
        tag
        for record in result.android_events + result.temperature_samples + result.auxiliary_events + result.sessions
        for tag in record.get("risk_tags", [])
    }
    if result.unknown_patterns:
        risk_tags.add("unknown_pattern_detected")
    session_counts = {name: 0 for name in ("cooking", "protect_pot", "recipe_recording", "manual_action", "idle_or_system", "unknown")}
    for session in result.sessions:
        session_counts[session["session_type"]] = session_counts.get(session["session_type"], 0) + 1
    return {
        "parser_version": LOG_SEMANTICS_VERSION, "schema_version": SCHEMA_VERSION,
        "parsed_at": datetime.now(ZoneInfo(timezone)).isoformat(timespec="seconds"),
        "input_dir": result.input_dir,
        "source_files": [item["source_file"] for item in result.file_inventory["files"]],
        "file_inventory": {k: v for k, v in result.file_inventory.items() if k.endswith("_file_count")},
        "time_range": {"start": min(timestamps) if timestamps else None, "end": max(timestamps) if timestamps else None},
        "counts": {
            "android_event_count": len(result.android_events), "temperature_sample_count": len(result.temperature_samples),
            "power_event_count": len(result.power_events), "action_event_count": len(result.action_events),
            "session_count": len(result.sessions), "unknown_pattern_count": len(result.unknown_patterns),
            "auxiliary_event_count": len(result.auxiliary_events),
            "command_event_counts": result.command_event_counts,
        },
        "thermal_summary": {
            "max_filtered_temp_c": _max(result.temperature_samples, "filtered_temp_c"),
            "max_infrared_temp_c": _max(result.temperature_samples, "infrared_temp_c"),
            "max_output_temp_c": _max(result.temperature_samples, "output_temp_c"),
            "max_android_output_temp_c": _max(result.power_events, "android_output_temp_c"),
        },
        "power_summary": {
            "max_command_power_w": _max(result.power_events, "command_power_w"),
            "max_command_power_kw": _max(result.power_events, "command_power_kw"),
            "max_actual_power_w": _max(result.power_events, "actual_power_w"),
            "max_actual_power_kw": _max(result.power_events, "actual_power_kw"),
        },
        "session_summary": session_counts, "risk_tags": sorted(risk_tags),
        "warnings": result.warnings, "parse_errors": result.parse_errors,
    }
