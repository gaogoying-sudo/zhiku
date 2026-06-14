from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime
from typing import Any, Dict, List, Optional


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _session_for(timestamp: str, sessions: List[Dict[str, Any]],
                 session_starts: List[datetime]) -> Optional[Dict[str, Any]]:
    value = _dt(timestamp)
    index = bisect_right(session_starts, value) - 1
    if index >= 0:
        session = sessions[index]
        if value <= _dt(session["end_time"]):
            return session
    return None


def _nearest(timestamp: str, samples: List[Dict[str, Any]], sample_times: List[datetime]) -> tuple[Optional[Dict[str, Any]], Optional[float]]:
    if not samples:
        return None, None
    target = _dt(timestamp)
    index = bisect_left(sample_times, target)
    candidates = [i for i in (index - 1, index) if 0 <= i < len(samples)]
    best = min(candidates, key=lambda i: abs((sample_times[i] - target).total_seconds()))
    delta = (sample_times[best] - target).total_seconds()
    return (samples[best], delta) if abs(delta) <= 5 else (None, delta)


def build_timeline(events: List[Dict[str, Any]], temperatures: List[Dict[str, Any]],
                   sessions: List[Dict[str, Any]], auxiliary_events: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    auxiliary_events = auxiliary_events or []
    samples = sorted((s for s in temperatures if s.get("timestamp")), key=lambda s: (s["timestamp"], s["line_no"]))
    sample_times = [_dt(s["timestamp"]) for s in samples]
    ordered_sessions = sorted(sessions, key=lambda session: session["start_time"])
    session_starts = [_dt(session["start_time"]) for session in ordered_sessions]
    rows: List[Dict[str, Any]] = []
    first_time = min(
        (_dt(item["timestamp"]) for item in events + temperatures + auxiliary_events if item.get("timestamp")),
        default=None,
    )
    for item in events + temperatures + auxiliary_events:
        timestamp = item.get("timestamp")
        if not timestamp:
            continue
        session = _session_for(timestamp, ordered_sessions, session_starts)
        nearest, delta = (item, 0.0) if item["event_type"] == "temperature_sample" else _nearest(timestamp, samples, sample_times)
        action_label = item["event_type"] if item["event_type"].startswith(
            ("liquid_", "lean_", "roll_", "weigh_", "speech_")
        ) else None
        rows.append({
            "timestamp": timestamp,
            "relative_second": int((_dt(timestamp) - first_time).total_seconds()) if first_time else None,
            "source_file": item["source_file"], "line_no": item["line_no"],
            "source_type": (
                "temperature" if item["event_type"] == "temperature_sample"
                else item.get("source_type", "android")
            ),
            "event_type": item["event_type"], "session_id": session["session_id"] if session else None,
            "recipe_id": session.get("recipe_id") if session else item.get("recipe_id"),
            "recipe_name": session.get("recipe_name") if session else item.get("recipe_name"),
            "command_power_kw": item.get("command_power_kw"), "actual_power_kw": item.get("actual_power_kw"),
            "filtered_temp_c": (nearest or {}).get("filtered_temp_c"),
            "infrared_temp_c": (nearest or {}).get("infrared_temp_c"),
            "output_temp_c": (nearest or {}).get("output_temp_c"),
            "android_output_temp_c": item.get("android_output_temp_c"),
            "nearest_temperature_delta_seconds": delta,
            "nearest_temperature_window": _window(delta),
            "action_label": action_label, "risk_tags": item.get("risk_tags", []),
            "raw_line": item["raw_line"],
        })
    for session in sessions:
        for marker, timestamp in (("session_start", session["start_time"]), ("session_end", session["end_time"])):
            rows.append({
                "timestamp": timestamp, "relative_second": int((_dt(timestamp) - first_time).total_seconds()) if first_time else None,
                "source_file": None, "line_no": None, "source_type": "session", "event_type": marker,
                "session_id": session["session_id"], "recipe_id": session.get("recipe_id"),
                "recipe_name": session.get("recipe_name"), "risk_tags": session.get("risk_tags", []),
                "action_label": session["session_type"], "raw_line": session["start_evidence"] if marker == "session_start" else session["end_evidence"],
            })
    return sorted(rows, key=lambda row: (row["timestamp"], row.get("source_type") or "", row.get("line_no") or 0))


def _window(delta: Optional[float]) -> Optional[str]:
    if delta is None:
        return None
    absolute = abs(delta)
    if absolute <= 1:
        return "1s"
    if absolute <= 3:
        return "3s"
    if absolute <= 5:
        return "5s"
    return None
