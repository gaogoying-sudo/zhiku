from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LogRecord:
    source_file: str
    line_no: int
    raw_line: str
    timestamp: Optional[str]
    raw_timestamp: Optional[str]
    event_type: str
    confidence: float = 1.0
    fields: Dict[str, Any] = field(default_factory=dict)
    risk_tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        fields = result.pop("fields")
        result.update(fields)
        return result


@dataclass
class ParseResult:
    input_dir: str
    file_inventory: Dict[str, Any]
    android_events: List[Dict[str, Any]] = field(default_factory=list)
    temperature_samples: List[Dict[str, Any]] = field(default_factory=list)
    power_events: List[Dict[str, Any]] = field(default_factory=list)
    action_events: List[Dict[str, Any]] = field(default_factory=list)
    command_events: List[Dict[str, Any]] = field(default_factory=list)
    auxiliary_events: List[Dict[str, Any]] = field(default_factory=list)
    sessions: List[Dict[str, Any]] = field(default_factory=list)
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    unknown_patterns: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    parse_errors: List[str] = field(default_factory=list)
    command_event_counts: Dict[str, int] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
