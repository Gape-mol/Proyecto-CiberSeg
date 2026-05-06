from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import Repository


# Defines the common result structure returned by all stages.
@dataclass
class StageResult:
    repo_id: int
    repo_full_name: str
    stage: str
    success: bool
    duration_s: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# Returns the repository id for a stage result.
def repo_id(repo: Repository) -> int:
    assert repo.id is not None
    return repo.id
