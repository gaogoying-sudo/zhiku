from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime
from typing import Any, Dict, List, Optional

STRONG_STARTS = {"cooking_start", "protect_pot_marker", "recipe_recording"}
KEY_EVENTS = {
    "cooking_start", "protect_pot_marker", "recipe_recording", "scene_change", "activity_lifecycle",
    "command_power_set", "command_power_result", "power_feedback", "liquid_feed_start",
    "lean_start", "roll_start", "weigh_start", "speech_start",
}


def _dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def _start_type(event: Dict[str, Any]) -> Optional[str]:
    event_type = event["event_type"]
    if event_type == "cooking_start":
        return "cooking"
    if event_type == "protect_pot_marker":
        return "protect_pot"
    if event_type == "recipe_recording":
        return "recipe_recording"
    if event_type == "activity_lifecycle" and event.get("lifecycle_action") == "onCreate":
        activity = event.get("activity_name")
        if activity == "ProtectPotActivity":
            return "protect_pot"
        if activity in {"NewCookingActivity", "RecipeMessageActivity"}:
            return "cooking"
    if event_type == "scene_change" and event.get("scene_name") == "COOKING":
        return "cooking"
    return None


def _is_end(event: Dict[str, Any], session_type: str) -> Optional[str]:
    if event["event_type"] in {"command_power_set", "command_power_result"} and event.get("command_power_w") == 0:
        return "power_zero"
    if event["event_type"] in {"roll_start", "roll_success"} and event.get("roll_mode") == "STOP_CW_ZERO":
        return "roll_stop"
    if event["event_type"] == "activity_lifecycle" and event.get("lifecycle_action") == "onDestroy":
        if session_type == "protect_pot" and event.get("activity_name") == "ProtectPotActivity":
            return "activity_destroy"
    if event["event_type"] == "scene_change" and event.get("scene_name") != "COOKING" and session_type == "cooking":
        return "scene_exit"
    return None


def build_sessions(events: List[Dict[str, Any]], temperatures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered = sorted((event for event in events if event.get("timestamp")), key=lambda e: (e["timestamp"], e["source_file"], e["line_no"]))
    temperature_ordered = sorted((item for item in temperatures if item.get("timestamp")), key=lambda item: item["timestamp"])
    temperature_times = [_dt(item["timestamp"]) for item in temperature_ordered]
    sessions: List[Dict[str, Any]] = []
    active: Optional[Dict[str, Any]] = None

    def close(end_event: Dict[str, Any], reason: str) -> None:
        nonlocal active
        if not active:
            return
        active["end_event"] = end_event
        active["end_reason"] = reason
        sessions.append(_finalize(active, temperature_ordered, temperature_times))
        active = None

    for event in ordered:
        start_type = _start_type(event)
        event_time = _dt(event["timestamp"])
        if active and event_time and active["last_key_time"] and (event_time - active["last_key_time"]).total_seconds() > 120:
            close(active["events"][-1], "120_second_inactivity")
        if start_type:
            if active:
                same_marker = active["session_type"] == start_type and (event_time - _dt(active["start_event"]["timestamp"])).total_seconds() <= 5
                if not same_marker:
                    close(active["events"][-1], "next_strong_start")
            if not active:
                active = {
                    "session_type": start_type, "start_event": event, "events": [],
                    "last_key_time": event_time,
                }
        if active:
            active["events"].append(event)
            if event["event_type"] in KEY_EVENTS:
                active["last_key_time"] = event_time
            reason = _is_end(event, active["session_type"])
            if reason and event is not active["start_event"]:
                close(event, reason)
    if active:
        close(active["events"][-1], "end_of_log")
    return sessions


def _finalize(active: Dict[str, Any], temperatures: List[Dict[str, Any]],
              temperature_times: List[datetime]) -> Dict[str, Any]:
    events = active["events"]
    start_event = active["start_event"]
    end_event = active["end_event"]
    start, end = _dt(start_event["timestamp"]), _dt(end_event["timestamp"])
    session_id = f"log-{start.strftime('%Y%m%d%H%M%S')}-{len(events):04d}"
    left = bisect_left(temperature_times, start)
    right = bisect_right(temperature_times, end)
    samples = temperatures[left:right]
    power = [e for e in events if e["event_type"] in {"command_power_set", "command_power_result", "power_feedback"}]
    actions = [e for e in events if e["event_type"].startswith(("liquid_", "lean_", "roll_", "weigh_", "speech_"))]
    risks = sorted({tag for item in events + samples for tag in item.get("risk_tags", [])})
    if active["session_type"] == "protect_pot" and _max(samples, "output_temp_c") and _max(samples, "output_temp_c") > 250:
        risks.append("protect_pot_high_temp")
    if not samples:
        risks.append("temperature_missing")
    if not any(e["event_type"] == "power_feedback" for e in power):
        risks.append("power_feedback_missing")
    command_energy, actual_energy = _integrate_power(power)
    result = {
        "session_id": session_id, "session_type": active["session_type"],
        "start_time": start_event["timestamp"], "end_time": end_event["timestamp"],
        "duration_seconds": max(0, int((end - start).total_seconds())),
        "recipe_name": next((e.get("recipe_name") for e in events if e.get("recipe_name")), None),
        "recipe_id": next((e.get("recipe_id") for e in events if e.get("recipe_id")), None),
        "source": "internal_log", "start_evidence": start_event["raw_line"],
        "end_evidence": end_event["raw_line"], "end_reason": active["end_reason"],
        "event_count": len(events), "temperature_sample_count": len(samples),
        "power_event_count": len(power), "action_event_count": len(actions),
        "liquid_feed_count": _count(events, "liquid_"), "lean_event_count": _count(events, "lean_"),
        "roll_event_count": _count(events, "roll_"), "weigh_event_count": _count(events, "weigh_"),
        "speech_event_count": _count(events, "speech_"),
        "max_filtered_temp_c": _max(samples, "filtered_temp_c"),
        "max_infrared_temp_c": _max(samples, "infrared_temp_c"),
        "max_output_temp_c": _max(samples, "output_temp_c"),
        "avg_output_temp_c": _avg(samples, "output_temp_c"),
        "first_output_temp_c": samples[0].get("output_temp_c") if samples else None,
        "last_output_temp_c": samples[-1].get("output_temp_c") if samples else None,
        "max_android_output_temp_c": _max(power, "android_output_temp_c"),
        "max_command_power_w": _max(power, "command_power_w"),
        "max_command_power_kw": _max(power, "command_power_kw"),
        "max_actual_power_w": _max(power, "actual_power_w"),
        "max_actual_power_kw": _max(power, "actual_power_kw"),
        "command_energy_kj": command_energy, "actual_energy_kj": actual_energy,
        "risk_tags": sorted(set(risks)),
        "evidence_lines": [e["raw_line"] for e in events[:5]] + ([events[-1]["raw_line"]] if len(events) > 5 else []),
    }
    return result


def _count(events: List[Dict[str, Any]], prefix: str) -> int:
    return sum(1 for event in events if event["event_type"].startswith(prefix))


def _max(records: List[Dict[str, Any]], key: str) -> Optional[float]:
    values = [record[key] for record in records if record.get(key) is not None]
    return max(values) if values else None


def _avg(records: List[Dict[str, Any]], key: str) -> Optional[float]:
    values = [record[key] for record in records if record.get(key) is not None]
    return round(sum(values) / len(values), 3) if values else None


def _integrate_power(events: List[Dict[str, Any]]) -> tuple[float, float]:
    ordered = sorted((e for e in events if e.get("timestamp")), key=lambda e: e["timestamp"])
    command_kj = actual_kj = 0.0
    for current, following in zip(ordered, ordered[1:]):
        seconds = min(60.0, max(0.0, (_dt(following["timestamp"]) - _dt(current["timestamp"])).total_seconds()))
        command_kj += (current.get("command_power_w") or 0) * seconds / 1000.0
        actual_kj += (current.get("actual_power_w") or 0) * seconds / 1000.0
    return round(command_kj, 3), round(actual_kj, 3)
