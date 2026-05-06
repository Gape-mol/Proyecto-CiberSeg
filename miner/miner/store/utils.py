from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


# Returns the current UTC timestamp as ISO string.
def now_str() -> str:
    return datetime.now(UTC).isoformat()


# Parses ISO timestamps from GitHub API into datetime.
def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# Converts an ISO string into a normalized ISO timestamp.
def parse_iso(value: str | None) -> str | None:
    dt = parse_dt(value)
    return dt.isoformat() if dt else None


# Converts datetime objects to ISO strings.
def dt_str(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# Builds a file location string including line information when present.
def file_location(file_path: str | None, line: Any = None) -> str | None:
    if not file_path:
        return None
    if isinstance(line, int):
        return f"{file_path}:{line}"
    return file_path
