"""Log format detection and parsing helpers."""
import json
import re
from datetime import datetime

SYSLOG_PATTERN = re.compile(
    r"^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(\S+?):\s*(.*)"
)
TIMESTAMP_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})"
)
# For normalizing error messages (replace variable parts)
NORMALIZE_PATTERNS = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "<UUID>"),
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "<IP>"),
    (re.compile(r"\b\d+\b"), "<NUM>"),
]


def detect_format(lines: list[str]) -> str:
    """Detect log format from first few lines."""
    sample = [l.strip() for l in lines[:5] if l.strip()]
    if not sample:
        return "plaintext"
    if all(l.startswith("{") for l in sample):
        return "jsonl"
    if all(SYSLOG_PATTERN.match(l) for l in sample):
        return "syslog"
    return "plaintext"


def normalize_message(msg: str) -> str:
    """Replace variable parts with placeholders for grouping."""
    for pattern, replacement in NORMALIZE_PATTERNS:
        msg = pattern.sub(replacement, msg)
    return msg
