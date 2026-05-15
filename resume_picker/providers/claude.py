from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from ..models import Dialogue, ProviderConfig, Session
from ..text import normalize_text, one_line


HARNESS_BLOCK_RE = re.compile(r"<([a-zA-Z][\w-]*)\b[^>]*>.*?</\1>", re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
INTERRUPT_RE = re.compile(r"^\[Request interrupted by user(?: for tool use)?\]$")


def resolve_command(env_name: str, command: str) -> str | None:
    explicit = os.environ.get(env_name)
    if explicit:
        return explicit
    return shutil.which(command)


def config_for_mode() -> ProviderConfig:
    return ProviderConfig(
        mode="claude",
        session_label="Claude Code",
        resume_command="claude",
        resume_env="CLAUDE_BIN",
        resume_bin=resolve_command("CLAUDE_BIN", "claude"),
        temp_prefix="claude-resume-",
        resume_args=("--resume",),
        resume_message="Resuming Claude session in:",
    )


class ClaudeProvider:
    def __init__(self) -> None:
        self.config = config_for_mode()
        self.projects_dir = Path(os.environ.get("CLAUDE_PROJECTS_DIR", str(Path.home() / ".claude" / "projects")))

    def load_sessions(self) -> list[Session]:
        if not self.projects_dir.exists():
            return []
        sessions: list[Session] = []
        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for path in project_dir.glob("*.jsonl"):
                session = self.extract_session(path)
                if session:
                    sessions.append(session)
        sessions.sort(key=lambda item: item.updated_sort_key, reverse=True)
        return sessions

    def extract_session(self, path: Path) -> Session | None:
        try:
            stat = path.stat()
        except OSError:
            return None

        custom_title = ""
        first_user_message = ""
        message_count = 0
        cwd = ""
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not cwd and isinstance(entry.get("cwd"), str):
                        cwd = entry["cwd"]
                    entry_type = entry.get("type", "")
                    if entry_type == "custom-title":
                        custom_title = str(entry.get("customTitle") or "")
                    elif entry_type == "user":
                        text = extract_claude_text(entry.get("message", ""), "user")
                        if entry.get("toolUseResult") or text.lstrip().startswith("<"):
                            continue
                        cleaned = clean_user_text(text)
                        if not cleaned:
                            continue
                        message_count += 1
                        if not first_user_message and not is_claude_interrupt_marker(cleaned):
                            first_user_message = cleaned
                    elif entry_type == "assistant":
                        text = extract_claude_text(entry.get("message", {}), "assistant").strip()
                        if not text:
                            continue
                        message_count += 1
        except (OSError, UnicodeDecodeError):
            return None

        if message_count == 0:
            return None
        if not first_user_message and not custom_title:
            return None

        updated_at = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat()
        title = custom_title or one_line(first_user_message, 110)
        return Session(
            id=path.stem,
            title=one_line(title, 110),
            cwd=cwd or dir_name_to_path(path.parent.name),
            provider="claude",
            created_at=updated_at,
            updated_at=updated_at,
            path=path,
            renamed=bool(custom_title),
        )

    def parse_dialogues(self, session: Session) -> list[Dialogue]:
        dialogues: list[Dialogue] = []
        num = 0
        continues_previous = False
        try:
            with session.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    entry_type = entry.get("type", "")
                    if entry_type == "user":
                        text = extract_claude_text(entry.get("message", ""), "user")
                        if entry.get("toolUseResult") or text.lstrip().startswith("<"):
                            continue
                        cleaned = normalize_text(clean_user_text(text))
                        if not cleaned:
                            continue
                        num += 1
                        is_interrupt = is_claude_interrupt_marker(cleaned)
                        dialogues.append(
                            Dialogue(
                                role="user",
                                num=num,
                                text=cleaned,
                                continues_previous=continues_previous or is_interrupt,
                            )
                        )
                        continues_previous = is_interrupt
                    elif entry_type == "assistant":
                        message = entry.get("message", {})
                        text = normalize_text(extract_claude_text(message, "assistant"))
                        tool_summaries = extract_claude_tool_summaries(message)
                        if not text:
                            if tool_summaries and dialogues and dialogues[-1].role == "assistant":
                                dialogues[-1].tool_summaries += tool_summaries
                            continue
                        num += 1
                        dialogues.append(Dialogue(role="assistant", num=num, text=text, tool_summaries=tool_summaries))
        except (OSError, UnicodeDecodeError):
            pass
        return dialogues


def dir_name_to_path(dir_name: str) -> str:
    return dir_name.replace("-", "/", 1).replace("-", "/")


def clean_user_text(text: str) -> str:
    text = HARNESS_BLOCK_RE.sub("", text)
    text = TAG_RE.sub("", text)
    return text.strip()


def is_claude_interrupt_marker(text: str) -> bool:
    return bool(INTERRUPT_RE.match(text.strip()))


def extract_claude_text(message: object, role: str) -> str:
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return ""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            block_type = block.get("type")
            if block_type == "text":
                parts.append(str(block.get("text") or ""))
            elif block_type == "image" and role == "user":
                parts.append("[image]")
    return "\n".join(parts)


def extract_claude_tool_summaries(message: object) -> tuple[str, ...]:
    if not isinstance(message, dict):
        return ()
    content = message.get("content", "")
    if not isinstance(content, list):
        return ()
    summaries: list[str] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        summary = summarize_claude_tool_use(block)
        if summary:
            summaries.append(summary)
    return tuple(summaries)


def summarize_claude_tool_use(block: dict) -> str:
    name = str(block.get("name") or "tool")
    payload = block.get("input")
    detail = ""
    if isinstance(payload, dict):
        for key in ("command", "file_path", "path", "url", "query"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                detail = value.strip()
                break
    return one_line(f"{name} {detail}".strip(), 140)
