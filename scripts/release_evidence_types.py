"""Shared release evidence data types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandOutcome:
    exit_code: int
    stdout: str = ""
    stderr: str = ""

@dataclass(frozen=True)
class EvidenceInput:
    kind: str
    path: Path | None
    source_path: Path | None
    required: bool
    source: str
