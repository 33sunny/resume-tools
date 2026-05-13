from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from ..models import Dialogue, ProviderConfig, Session, parse_iso
from ..text import normalize_text, one_line


CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
CODEX_PROVIDER = os.environ.get("CODEX_PROVIDER", "openai")
CODEX_SOURCE = os.environ.get("CODEX_SOURCE", "cli")
CODEX_PROXY_PROVIDER = os.environ.get("CODEX_PROXY_PROVIDER", "cliproxy")
CODEX_PROXY_SOURCE = os.environ.get("CODEX_PROXY_SOURCE", "cli")


def resolve_command(env_name: str, command: str) -> str | None:
    explicit = os.environ.get(env_name)
    if explicit:
        return explicit
    return shutil.which(command)


def newest_timestamp(*values: str) -> str:
    newest = ""
    newest_sort = float("-inf")
    for value in values:
        parsed = parse_iso(str(value or ""))
        if parsed is None:
            continue
        sort_key = parsed.timestamp()
        if sort_key > newest_sort:
            newest = str(value)
            newest_sort = sort_key
    return newest


def meaningful_title(text: str) -> bool:
    return bool(text.strip()) and text.strip().lower() not in {"(untitled)", "untitled"}


def config_for_mode(mode: str) -> ProviderConfig:
    if mode == "codex":
        return ProviderConfig(
            mode="codex",
            session_label="Codex CLI",
            resume_command="codex",
            resume_env="CODEX_BIN",
            resume_bin=resolve_command("CODEX_BIN", "codex"),
            temp_prefix="codex-resume-",
            resume_args=("resume",),
            resume_message="Resuming Codex session in:",
        )
    return ProviderConfig(
        mode="proxy",
        session_label="codex-proxy",
        resume_command="codex-proxy",
        resume_env="CODEX_PROXY_BIN",
        resume_bin=resolve_command("CODEX_PROXY_BIN", "codex-proxy"),
        temp_prefix="codex-proxy-resume-",
        resume_args=("resume",),
        resume_message="Resuming Codex session in:",
    )


class CodexProvider:
    def __init__(self, mode: str) -> None:
        self.config = config_for_mode(mode)
        if mode == "codex":
            self.provider = CODEX_PROVIDER
            self.source = CODEX_SOURCE
        else:
            self.provider = CODEX_PROXY_PROVIDER
            self.source = CODEX_PROXY_SOURCE

    def load_index(self) -> dict[str, dict[str, object]]:
        index_path = CODEX_HOME / "session_index.jsonl"
        entries: dict[str, dict[str, object]] = {}
        if not index_path.exists():
            return entries
        with index_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_id = entry.get("id")
                if session_id:
                    raw_title = str(entry.get("thread_name") or "(untitled)")
                    entries[session_id] = {
                        "title": one_line(raw_title, 110),
                        "raw_title": raw_title,
                        "updated_at": entry.get("updated_at") or "",
                    }
        return entries

    def read_session_meta(self, path: Path) -> dict[str, str] | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for index, line in enumerate(handle):
                    if index > 30:
                        break
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("type") != "session_meta":
                        continue
                    payload = entry.get("payload")
                    if not isinstance(payload, dict):
                        return None
                    session_id = payload.get("id")
                    cwd = payload.get("cwd")
                    if not isinstance(session_id, str) or not isinstance(cwd, str):
                        return None
                    return {
                        "id": session_id,
                        "cwd": cwd,
                        "provider": str(payload.get("model_provider") or "-"),
                        "source": str(payload.get("source") or ""),
                        "thread_source": str(payload.get("thread_source") or ""),
                        "created_at": str(payload.get("timestamp") or entry.get("timestamp") or ""),
                    }
        except (OSError, UnicodeDecodeError):
            pass
        return None

    def read_thread_name_update(self, path: Path) -> tuple[str, str, str]:
        title = ""
        updated_at = ""
        latest_at = ""
        latest_sort = float("-inf")
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    entry_timestamp = str(entry.get("timestamp") or "")
                    parsed_timestamp = parse_iso(entry_timestamp)
                    if parsed_timestamp is not None:
                        sort_key = parsed_timestamp.timestamp()
                        if sort_key > latest_sort:
                            latest_at = entry_timestamp
                            latest_sort = sort_key
                    if entry.get("type") != "event_msg":
                        continue
                    payload = entry.get("payload")
                    if not isinstance(payload, dict) or payload.get("type") != "thread_name_updated":
                        continue
                    thread_name = payload.get("thread_name")
                    if isinstance(thread_name, str) and thread_name.strip():
                        title = one_line(thread_name, 110)
                        updated_at = entry_timestamp
        except (OSError, UnicodeDecodeError):
            pass
        return title, updated_at, latest_at

    def load_sessions(self) -> list[Session]:
        index = self.load_index()
        sessions_dir = CODEX_HOME / "sessions"
        if not sessions_dir.exists():
            return []

        sessions: list[Session] = []
        for path in sessions_dir.glob("**/*.jsonl"):
            meta = self.read_session_meta(path)
            if not meta:
                continue
            if meta["provider"] != self.provider:
                continue
            if self.source and meta.get("source") not in ("", self.source):
                continue
            session_id = meta["id"]
            index_entry = index.get(session_id, {})
            title_from_event, event_title_updated_at, latest_file_event_at = self.read_thread_name_update(path)
            title_from_index = str(index_entry.get("title") or "")
            index_updated_at = str(index_entry.get("updated_at") or "")
            use_index_title = bool(title_from_index) and (
                not title_from_event
                or (
                    title_from_index != title_from_event
                    and parse_iso(index_updated_at) is not None
                    and parse_iso(event_title_updated_at) is not None
                    and parse_iso(index_updated_at) > parse_iso(event_title_updated_at)
                )
            )
            title = title_from_index if use_index_title else title_from_event
            renamed = bool(title_from_event) or bool(
                meaningful_title(title_from_index) and meta.get("thread_source") == "user"
            )
            try:
                file_mtime = datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()
            except OSError:
                file_mtime = ""
            updated_at = newest_timestamp(index_updated_at, latest_file_event_at, file_mtime) or meta["created_at"]
            sessions.append(
                Session(
                    id=session_id,
                    title=str(title or self.fallback_title(path)),
                    cwd=meta["cwd"],
                    provider=self.config.resume_command,
                    created_at=meta["created_at"],
                    updated_at=str(updated_at),
                    path=path,
                    renamed=renamed,
                )
            )
        sessions.sort(key=lambda item: item.updated_sort_key, reverse=True)
        return sessions

    def fallback_title(self, path: Path) -> str:
        for dialogue in self.parse_dialogues_path(path):
            if dialogue.role == "user":
                return one_line(dialogue.text, 110)
        return "(untitled)"

    def parse_dialogues(self, session: Session) -> list[Dialogue]:
        return self.parse_dialogues_path(session.path)

    def parse_dialogues_path(self, path: Path) -> list[Dialogue]:
        dialogues: list[Dialogue] = []
        num = 0
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("type") == "event_msg":
                        payload = entry.get("payload")
                        if not isinstance(payload, dict) or payload.get("type") != "user_message":
                            continue
                        text = normalize_text(str(payload.get("message") or ""))
                        if is_noise_message("user", text):
                            continue
                        if dialogues and dialogues[-1].role == "user" and dialogues[-1].text == text:
                            continue
                        num += 1
                        dialogues.append(Dialogue(role="user", num=num, text=text))
                        continue
                    if entry.get("type") != "response_item":
                        continue
                    payload = entry.get("payload")
                    if not isinstance(payload, dict) or payload.get("type") != "message":
                        continue
                    role = str(payload.get("role") or "")
                    if role not in ("user", "assistant"):
                        continue
                    text = normalize_text("\n".join(extract_text_blocks(payload.get("content"), role)))
                    if is_noise_message(role, text):
                        continue
                    num += 1
                    dialogues.append(Dialogue(role=role, num=num, text=text))
        except (OSError, UnicodeDecodeError):
            pass
        return dialogues


def extract_text_blocks(content: object, role: str) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    texts: list[str] = []
    for block in content:
        if isinstance(block, str):
            texts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str):
            texts.append(text)
        elif block.get("type") == "image" and role == "user":
            texts.append("[image]")
    return texts


def is_noise_message(role: str, text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return role == "user" and stripped.startswith("<")
