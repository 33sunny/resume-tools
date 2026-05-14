from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class PlanStep:
    step: str
    status: str


@dataclass
class PlanUpdate:
    steps: tuple[PlanStep, ...]
    explanation: str = ""


@dataclass
class DialogueActivity:
    kind: str
    text: str = ""
    plan_update: PlanUpdate | None = None


@dataclass
class Dialogue:
    role: str
    num: int
    text: str
    tool_summaries: tuple[str, ...] = ()
    plan_updates: tuple[PlanUpdate, ...] = ()
    activities: tuple[DialogueActivity, ...] = ()
    continues_previous: bool = False


@dataclass
class DialogueBlock:
    num: int
    start_num: int
    end_num: int
    dialogues: list[Dialogue]


@dataclass
class Session:
    id: str
    title: str
    cwd: str
    provider: str
    created_at: str
    updated_at: str
    path: Path
    renamed: bool = False

    @property
    def updated_sort_key(self) -> float:
        parsed = parse_iso(self.updated_at) or parse_iso(self.created_at)
        return parsed.timestamp() if parsed is not None else 0.0


@dataclass(frozen=True)
class ProviderConfig:
    mode: str
    session_label: str
    resume_command: str
    resume_env: str
    resume_bin: str | None
    temp_prefix: str
    resume_args: tuple[str, ...]
    resume_message: str
