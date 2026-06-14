"""Integration-ready device log semantics parser."""

LOG_SEMANTICS_VERSION = "0.1.0"
SCHEMA_VERSION = "log_semantics_v1"

from .parser import parse_log_directory

__all__ = ["LOG_SEMANTICS_VERSION", "SCHEMA_VERSION", "parse_log_directory"]
