from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import Dialogue, DialogueBlock, ProviderConfig, Session
from .text import (
    BOLD,
    CYAN,
    DIM,
    HIGHLIGHT,
    MAGENTA,
    RESET,
    WHITE,
    YELLOW,
    compact_divider,
    format_date_label,
    format_row_time,
    format_time,
    full_width_divider,
    highlight_matches,
    one_line,
    render_markdown_lines,
    visual_text_width,
    visual_truncate,
    wrap_visual,
    week_label,
)


INTERRUPT = "\033[1;31m"
PLAN_ACTIVE = "\033[38;2;142;236;211m"
STRIKE = "\033[9m"
ANSI_RE = re.compile(r"\033\[[0-9;:]*m")


class Provider(Protocol):
    config: ProviderConfig

    def load_sessions(self) -> list[Session]:
        ...

    def parse_dialogues(self, session: Session) -> list[Dialogue]:
        ...


def preview_cols() -> int:
    value = os.environ.get("FZF_PREVIEW_COLUMNS", "")
    return int(value) if value.isdigit() else 100


def preview_height() -> int:
    value = os.environ.get("FZF_PREVIEW_LINES", "")
    return max(5, int(value)) if value.isdigit() else 24


def dialogue_blocks(dialogues: list[Dialogue]) -> list[DialogueBlock]:
    blocks: list[DialogueBlock] = []
    current: list[Dialogue] = []
    current_has_assistant = False
    for dialogue in dialogues:
        if dialogue.role == "user" and current_has_assistant and not dialogue.continues_previous:
            if current:
                blocks.append(make_dialogue_block(len(blocks) + 1, current))
            current = [dialogue]
            current_has_assistant = False
        else:
            current.append(dialogue)
            if dialogue.role != "user":
                current_has_assistant = True
    if current:
        blocks.append(make_dialogue_block(len(blocks) + 1, current))
    return blocks


def make_dialogue_block(num: int, dialogues: list[Dialogue]) -> DialogueBlock:
    return DialogueBlock(num, dialogues[0].num, dialogues[-1].num, dialogues)


def dialogue_role_groups(dialogues: list[Dialogue]) -> list[list[Dialogue]]:
    groups: list[list[Dialogue]] = []
    for dialogue in dialogues:
        if groups and groups[-1][0].role == dialogue.role:
            groups[-1].append(dialogue)
        else:
            groups.append([dialogue])
    return groups


class Picker:
    def __init__(self, provider: Provider, script_path: Path, mode: str) -> None:
        self.provider = provider
        self.config = provider.config
        self.script_path = script_path
        self.mode = mode

    def session_by_id(self, session_id: str) -> Session | None:
        return next((session for session in self.provider.load_sessions() if session.id == session_id), None)

    def filter_sessions(self, cwd: str, include_all: bool, keyword: str = "") -> list[Session]:
        sessions = self.provider.load_sessions()
        filtered = sessions if include_all else [session for session in sessions if session.cwd == cwd]
        if not keyword:
            return filtered
        needle = keyword.lower()
        result: list[Session] = []
        for session in filtered:
            if needle in session.title.lower() or needle in session.cwd.lower():
                result.append(session)
                continue
            if any(needle in dialogue_search_blob(dialogue).lower() for dialogue in self.provider.parse_dialogues(session)):
                result.append(session)
        return result

    def message_count(self, session: Session) -> int:
        return len(self.provider.parse_dialogues(session))

    def is_summary_noise(self, text: str) -> bool:
        stripped = text.lstrip()
        noise_prefixes = (
            "# AGENTS.md instructions",
            "# Configure Claude HUD",
            "Another language model started to solve this problem",
        )
        return any(stripped.startswith(prefix) for prefix in noise_prefixes)

    def session_message_summary(self, session: Session) -> str:
        for dialogue in self.provider.parse_dialogues(session):
            if dialogue.role == "user" and not self.is_summary_noise(dialogue.text):
                return one_line(dialogue.text, 96)
        return one_line(session.title, 96)

    def session_display_title(self, session: Session) -> str:
        summary = self.session_message_summary(session)
        if session.renamed:
            return one_line(f"★ {session.title} · {summary}", 140)
        return f"  {summary}"

    def session_row(self, session: Session) -> str:
        dialogues = self.provider.parse_dialogues(session)
        return "\t".join(
            [
                session.id,
                format_row_time(session.updated_at),
                self.session_display_title(session),
                session.cwd,
                f"{len(dialogues)} dialogues",
                f"[{session.id[:8]}]",
                session.provider,
                session_search_blob(session, dialogues),
            ]
        )

    def session_rows(self, sessions: list[Session]) -> str:
        rows: list[str] = []
        current_week = ""
        current_day = ""
        now = datetime.now().astimezone()
        for session in sessions:
            timestamp = session.updated_at or session.created_at
            week = week_label(timestamp, now)
            if week != current_week:
                if rows:
                    rows.append(blank_divider())
                current_week = week
                current_day = ""
                rows.append(f"__DIVIDER__\t{BOLD}{DIM}{full_width_divider(week)}{RESET}\t\t\t\t\t\t")
            day = format_date_label(timestamp, now)
            if day != current_day:
                current_day = day
                rows.append(f"__DIVIDER__\t{BOLD}{DIM}{compact_divider(day)}{RESET}\t\t\t\t\t\t")
            rows.append(self.session_row(session))
        return "\n".join(rows)

    def dialogues_rows(self, session: Session, highlight: str = "") -> str:
        rows: list[str] = []
        dialogues = self.provider.parse_dialogues(session)
        if not dialogues:
            return ""
        num_width = len(str(dialogues[-1].num))
        pattern = re.compile(re.escape(highlight), re.IGNORECASE) if highlight else None
        for dialogue in dialogues:
            text = one_line(dialogue.text, 100)
            text_style = "" if dialogue.role == "user" else DIM
            if pattern:
                text = pattern.sub(lambda match: f"{HIGHLIGHT}{match.group()}{RESET}{text_style}", text)
            icon = "👤" if dialogue.role == "user" else "🤖"
            color = CYAN if dialogue.role == "user" else YELLOW
            label = f"{color}{dialogue.num:>{num_width}}.{RESET} {icon} {text_style}{text}{RESET}"
            rows.append(row_with_hidden_search(dialogue.num, label, dialogue_search_blob(dialogue)))
        return "\n".join(rows)

    def dialogue_block_rows(self, session: Session, highlight: str = "") -> str:
        rows: list[str] = []
        blocks = dialogue_blocks(self.provider.parse_dialogues(session))
        if not blocks:
            return ""
        num_width = len(str(blocks[-1].num))
        pattern = re.compile(re.escape(highlight), re.IGNORECASE) if highlight else None
        for block in blocks:
            user_dialogue = next((dialogue for dialogue in block.dialogues if dialogue.role == "user"), None)
            assistant_dialogue = next((dialogue for dialogue in block.dialogues if dialogue.role != "user"), None)
            if user_dialogue:
                text = f"👤 {one_line(user_dialogue.text, 74)}"
            else:
                text = f"🤖 {one_line(block.dialogues[0].text, 74)}"
            if assistant_dialogue and assistant_dialogue is not block.dialogues[0]:
                text = f"{text}  ·  🤖 {one_line(assistant_dialogue.text, 58)}"
            if pattern:
                text = pattern.sub(lambda match: f"{HIGHLIGHT}{match.group()}{RESET}", text)
            label = f"{MAGENTA}{block.num:>{num_width}}.{RESET} {text}"
            rows.append(row_with_hidden_search(block.num, label, block_search_blob(block)))
        return "\n".join(rows)

    def session_preview(self, session_id: str, keyword: str = "") -> int:
        if session_id == "__DIVIDER__" or not session_id:
            return 0
        session = self.session_by_id(session_id)
        if session is None:
            print(f"Session not found: {session_id}")
            return 1

        cols = preview_cols()
        dialogues = self.provider.parse_dialogues(session)
        title = one_line(session.title or (dialogues[0].text if dialogues else "(untitled)"), cols - 2)

        lines = [
            f"{WHITE}{title}{RESET}",
            f"{DIM}📁 {session.cwd}{RESET}",
            f"{DIM}📅 {format_time(session.updated_at)}  •  {len(dialogues)} dialogues  •  {session.provider}  •  ID {session.id}{RESET}",
            "",
        ]
        if keyword:
            lines.extend(search_dialogues_preview(dialogues, keyword, cols))
        else:
            lines.extend(dialogues_summary_preview(dialogues, cols))
        print("\n".join(lines))
        return 0

    def dialogue_preview(self, session_id: str, num: int, highlight: str = "", offset: int = 0) -> int:
        lines = self.dialogue_preview_lines(session_id, num, highlight)
        if lines is None:
            return 1
        print_preview_lines(lines, offset)
        return 0

    def dialogue_preview_lines(self, session_id: str, num: int, highlight: str = "") -> list[str] | None:
        session = self.session_by_id(session_id)
        if session is None:
            print(f"Session not found: {session_id}")
            return None
        dialogues = self.provider.parse_dialogues(session)
        target = next((dialogue for dialogue in dialogues if dialogue.num == num), None)
        if target is None:
            print(f"Message {num} not found.")
            return None

        cols = preview_cols()
        title = one_line(session.title or (dialogues[0].text if dialogues else "(untitled)"), cols - 2)
        role_label = "User" if target.role == "user" else self.config.session_label
        icon = "👤" if target.role == "user" else "🤖"
        color = CYAN if target.role == "user" else YELLOW
        lines = [
            f"{DIM}{title}{RESET}",
            f"{DIM}📁 {session.cwd}{RESET}",
            f"{DIM}ID {session.id}{RESET}",
            "",
            f"{BOLD}{color}{icon} {role_label} · message {target.num} of {len(dialogues)}{RESET}",
            f"{DIM}{'─' * max(1, cols - 2)}{RESET}",
        ]
        if target.text:
            lines.extend(highlight_rendered_lines(render_markdown_lines(target.text, cols), highlight))
        activity_lines = dialogue_activity_lines(target, cols)
        if activity_lines:
            if target.text:
                lines.append("")
            lines.extend(activity_lines)
        return lines

    def dialogue_block_preview(self, session_id: str, num: int, highlight: str = "", offset: int = 0) -> int:
        lines = self.dialogue_block_preview_lines(session_id, num, highlight)
        if lines is None:
            return 1
        print_preview_lines(lines, offset)
        return 0

    def dialogue_block_preview_lines(self, session_id: str, num: int, highlight: str = "") -> list[str] | None:
        session = self.session_by_id(session_id)
        if session is None:
            print(f"Session not found: {session_id}")
            return None
        dialogues = self.provider.parse_dialogues(session)
        blocks = dialogue_blocks(dialogues)
        target = next((block for block in blocks if block.num == num), None)
        if target is None:
            print(f"Round {num} not found.")
            return None

        cols = preview_cols()
        title = one_line(session.title or (dialogues[0].text if dialogues else "(untitled)"), cols - 2)
        lines = [
            f"{DIM}{title}{RESET}",
            f"{DIM}📁 {session.cwd}{RESET}",
            f"{DIM}ID {session.id}{RESET}",
            "",
            f"{BOLD}{MAGENTA}{preview_message_range_label(target.start_num, target.end_num, len(dialogues))}{RESET}",
        ]
        for group_index, group in enumerate(dialogue_role_groups(target.dialogues)):
            if group_index:
                lines.append("")
                if group[0].continues_previous:
                    lines.append(interrupt_divider(cols))
                lines.append("")
            lines.append(role_group_divider(group, self.config.session_label, cols))
            show_message_markers = len(group) > 1
            for message_index, dialogue in enumerate(group):
                if show_message_markers:
                    if message_index:
                        lines.append("")
                    lines.append(message_divider(dialogue.num, cols))
                if dialogue.text:
                    lines.extend(highlight_rendered_lines(render_markdown_lines(dialogue.text, cols), highlight))
                activity_lines = dialogue_activity_lines(dialogue, cols)
                if activity_lines:
                    if dialogue.text:
                        lines.append("")
                    lines.extend(activity_lines)
        return lines

    def next_match_index(self, session_id: str, keyword: str, from_pos: int, direction: int) -> int | None:
        session = self.session_by_id(session_id)
        if session is None or not keyword:
            return None
        dialogues = self.provider.parse_dialogues(session)
        if not dialogues:
            return None
        needle = keyword.lower()
        count = len(dialogues)
        for offset in range(1, count + 1):
            index = (from_pos + direction * offset) % count
            if needle in dialogues[index].text.lower():
                return index
        return None

    def next_block_match_index(self, session_id: str, keyword: str, from_pos: int, direction: int) -> int | None:
        session = self.session_by_id(session_id)
        if session is None or not keyword:
            return None
        blocks = dialogue_blocks(self.provider.parse_dialogues(session))
        if not blocks:
            return None
        needle = keyword.lower()
        count = len(blocks)
        for offset in range(1, count + 1):
            index = (from_pos + direction * offset) % count
            if needle in block_search_blob(blocks[index]).lower():
                return index
        return None

    def block_num_for_message(self, session_id: str, message_num: int) -> int | None:
        session = self.session_by_id(session_id)
        if session is None:
            return None
        for block in dialogue_blocks(self.provider.parse_dialogues(session)):
            if block.start_num <= message_num <= block.end_num:
                return block.num
        return None

    def first_message_num_for_block(self, session_id: str, block_num: int) -> int | None:
        session = self.session_by_id(session_id)
        if session is None:
            return None
        for block in dialogue_blocks(self.provider.parse_dialogues(session)):
            if block.num == block_num:
                return block.start_num
        return None

    def dialogue_preview_label_for_row(self, state_dir: Path, row_num: str, focused: bool) -> str:
        view = read_dialogue_view(state_dir)
        if view != "blocks" or not focused or not row_num.isdigit():
            return dialogue_preview_label(view, focused)
        session = self.session_by_id(read_text(state_dir / "session_id"))
        if session is None:
            return dialogue_preview_label(view, focused)
        total = len(dialogue_blocks(self.provider.parse_dialogues(session)))
        return f"▶ Round {row_num} of {total} · ↑↓ scroll · ⇧↑/⇧↓ page · F5 refresh · ← back"

    def update_preview_page_scroll(self, state_dir: Path, extra: list[str], direction: int) -> bool:
        row_num = extra[0] if len(extra) > 0 else ""
        fzf_query = extra[1] if len(extra) > 1 else ""
        keyword = fzf_query or read_text(state_dir / "keyword")
        key = preview_state_key(state_dir, row_num, keyword)
        offset = read_preview_offset(state_dir, key)
        cache = read_preview_cache(state_dir, key, preview_cols())
        if cache is None:
            write_preview_offset(state_dir, key, 0)
            return False
        lines, starts, anchors = cache
        next_offset = cached_preview_page_offset(len(lines), starts, anchors, offset, preview_height(), direction)
        write_preview_offset(state_dir, key, next_offset)
        return True

    def update_preview_line_scroll(self, state_dir: Path, extra: list[str], direction: int) -> bool:
        row_num = extra[0] if len(extra) > 0 else ""
        fzf_query = extra[1] if len(extra) > 1 else ""
        keyword = fzf_query or read_text(state_dir / "keyword")
        key = preview_state_key(state_dir, row_num, keyword)
        offset = read_preview_offset(state_dir, key)
        cache = read_preview_cache(state_dir, key, preview_cols())
        if cache is None:
            write_preview_offset(state_dir, key, 0)
            return False
        line_count = len(cache[0])
        next_offset = min(max(0, offset + direction), max(0, line_count - 1))
        write_preview_offset(state_dir, key, next_offset)
        return True

    def refresh_sessions(self, state_dir: Path, selected_session_id: str) -> int:
        keyword = read_text(state_dir / "keyword")
        include_all = read_text(state_dir / "include_all") == "1"
        cwd = read_text(state_dir / "scope_cwd") or os.getcwd()
        rows = self.session_rows(self.filter_sessions(cwd, include_all, ""))
        write_text(state_dir / "sessions.txt", rows)
        reset_preview_scroll(state_dir)
        filtered_rows = filter_rows_by_query(rows, keyword)
        position = session_row_position(filtered_rows, selected_session_id) or first_selectable_row_position(filtered_rows)
        print(f"reload-sync({self.helper_command(str(state_dir), 'list')})+pos({position})+refresh-preview")
        return 0

    def refresh_dialogues(self, state_dir: Path, row_num: str) -> int:
        reset_preview_scroll(state_dir)
        rows = self.rows_for_state(state_dir)
        position = row_position(rows, row_num) or first_selectable_row_position(rows)
        print(f"reload-sync({self.helper_command(str(state_dir), 'list')})+pos({position})+refresh-preview")
        return 0

    def helper_command(self, state_dir: str, *args: str) -> str:
        return quoted_command(sys.executable, str(self.script_path), "--mode", self.mode, "--helper", *args[:1], state_dir, *args[1:])

    def helper_main(self, state_dir: Path, action: str, extra: list[str]) -> int:
        if action == "list":
            print(self.rows_for_state(state_dir), end="")
            return 0

        if action == "search-transform":
            query = extra[0] if extra else ""
            write_text(state_dir / "keyword", query)
            reset_preview_scroll(state_dir)
            position = first_selectable_row_position(self.rows_for_state(state_dir))
            print(f"reload-sync({self.helper_command(str(state_dir), 'list')})+pos({position})+refresh-preview")
            return 0

        if action == "refresh-transform":
            row_num_or_session_id = extra[0] if len(extra) > 0 else ""
            if read_state_mode(state_dir) == "dialogues":
                return self.refresh_dialogues(state_dir, row_num_or_session_id)
            return self.refresh_sessions(state_dir, row_num_or_session_id)

        if action == "preview":
            field1 = extra[0] if len(extra) > 0 else ""
            fzf_query = extra[1] if len(extra) > 1 else ""
            if not field1 or field1 == "__DIVIDER__":
                return 0
            if read_state_mode(state_dir) == "dialogues":
                session_id = read_text(state_dir / "session_id")
                keyword = fzf_query or read_text(state_dir / "keyword")
                key = preview_state_key(state_dir, field1, keyword)
                cols = preview_cols()
                had_offset = read_text(state_dir / "preview_key") == key
                offset = read_preview_offset(state_dir, key)
                cache = read_preview_cache(state_dir, key, cols)
                if cache is not None:
                    lines = cache[0]
                else:
                    if read_dialogue_view(state_dir) == "blocks":
                        lines = self.dialogue_block_preview_lines(session_id, int(field1), keyword)
                    else:
                        lines = self.dialogue_preview_lines(session_id, int(field1), keyword)
                    if lines is None:
                        return 1
                    write_preview_cache(state_dir, key, lines, cols)
                if not had_offset and keyword:
                    offset = initial_keyword_offset(lines, keyword, preview_height())
                    write_preview_offset(state_dir, key, offset)
                print_preview_lines(lines, offset)
                return 0
            keyword = read_text(state_dir / "keyword")
            return self.session_preview(field1, keyword)

        if action == "up-transform":
            if read_state_mode(state_dir) == "dialogues" and read_state_focus(state_dir) == "preview":
                self.update_preview_line_scroll(state_dir, extra, -1)
                print("refresh-preview+preview-top")
            else:
                print("up")
            return 0

        if action == "down-transform":
            if read_state_mode(state_dir) == "dialogues" and read_state_focus(state_dir) == "preview":
                self.update_preview_line_scroll(state_dir, extra, 1)
                print("refresh-preview+preview-top")
            else:
                print("down")
            return 0

        if action == "page-up-transform":
            if read_state_mode(state_dir) == "dialogues":
                self.update_preview_page_scroll(state_dir, extra, -1)
                print("refresh-preview+preview-top")
            else:
                print("up")
            return 0

        if action == "page-down-transform":
            if read_state_mode(state_dir) == "dialogues":
                self.update_preview_page_scroll(state_dir, extra, 1)
                print("refresh-preview+preview-top")
            else:
                print("down")
            return 0

        if action == "right-transform":
            session_id = extra[0] if len(extra) > 0 else ""
            cwd = extra[1] if len(extra) > 1 else ""
            if read_state_mode(state_dir) == "dialogues":
                if read_state_focus(state_dir) != "preview":
                    write_text(state_dir / "focus", "preview")
                    print(
                        f"change-preview-label( {self.dialogue_preview_label_for_row(state_dir, session_id, True)} )"
                        f"+change-preview-window({dialogue_preview_window(True)})"
                    )
                return 0
            if not session_id or session_id == "__DIVIDER__":
                return 0
            write_text(state_dir / "mode", "dialogues")
            write_text(state_dir / "focus", "list")
            write_text(state_dir / "dialogue_view", "messages")
            write_text(state_dir / "session_id", session_id)
            write_text(state_dir / "cwd", cwd)
            unlink_if_exists(state_dir / "load_jump")
            reset_preview_scroll(state_dir)
            keyword = read_text(state_dir / "keyword")
            if keyword:
                index = self.next_match_index(session_id, keyword, -1, 1)
                if index is not None:
                    write_text(state_dir / "load_jump", str(index + 1))
            print(
                f"reload-sync({self.helper_command(str(state_dir), 'list')})"
                "+first+refresh-preview+change-border-label( Dialogues )+change-preview-label( Content )"
                f"+change-preview-window({dialogue_preview_window(False)})"
            )
            return 0

        if action == "left-transform":
            if read_state_mode(state_dir) == "dialogues" and read_state_focus(state_dir) == "preview":
                write_text(state_dir / "focus", "list")
                print(
                    f"change-preview-label( {dialogue_preview_label(read_dialogue_view(state_dir), False)} )"
                    f"+change-preview-window({dialogue_preview_window(False)})"
                )
                return 0
            if read_state_mode(state_dir) == "sessions":
                return 0
            write_text(state_dir / "mode", "sessions")
            write_text(state_dir / "focus", "list")
            for name in ("session_id", "cwd", "load_jump", "dialogue_view"):
                unlink_if_exists(state_dir / name)
            reset_preview_scroll(state_dir)
            print(
                f"reload-sync({self.helper_command(str(state_dir), 'list')})"
                f"+pos({first_selectable_row_position(self.rows_for_state(state_dir))})"
                "+refresh-preview+change-border-label( Sessions )+change-preview-label( Dialogues )"
                f"+change-preview-window({dialogue_preview_window(False)})"
            )
            return 0

        if action == "esc-transform":
            if read_state_mode(state_dir) == "dialogues" and read_state_focus(state_dir) == "preview":
                write_text(state_dir / "focus", "list")
                print(
                    f"change-preview-label( {dialogue_preview_label(read_dialogue_view(state_dir), False)} )"
                    f"+change-preview-window({dialogue_preview_window(False)})"
                )
                return 0
            if read_state_mode(state_dir) == "dialogues":
                write_text(state_dir / "mode", "sessions")
                write_text(state_dir / "focus", "list")
                for name in ("session_id", "cwd", "load_jump", "dialogue_view"):
                    unlink_if_exists(state_dir / name)
                reset_preview_scroll(state_dir)
                print(
                    f"reload-sync({self.helper_command(str(state_dir), 'list')})"
                    f"+pos({first_selectable_row_position(self.rows_for_state(state_dir))})"
                    "+refresh-preview+change-border-label( Sessions )+change-preview-label( Dialogues )"
                    f"+change-preview-window({dialogue_preview_window(False)})"
                )
            else:
                print("abort")
            return 0

        if action == "load-jump":
            position = read_text(state_dir / "load_jump")
            if position:
                unlink_if_exists(state_dir / "load_jump")
                print(f"pos({position})")
            return 0

        if action == "toggle-dialogue-view":
            if read_state_mode(state_dir) != "dialogues":
                return 0
            current_num = int(extra[0]) if len(extra) > 0 and extra[0].isdigit() else 1
            session_id = read_text(state_dir / "session_id")
            current_view = read_dialogue_view(state_dir)
            if current_view == "blocks":
                next_view = "messages"
                target_pos = self.first_message_num_for_block(session_id, current_num) or 1
            else:
                next_view = "blocks"
                target_pos = self.block_num_for_message(session_id, current_num) or 1
            write_text(state_dir / "dialogue_view", next_view)
            write_text(state_dir / "focus", "list")
            reset_preview_scroll(state_dir)
            rows = self.rows_for_state(state_dir)
            position = row_position(rows, str(target_pos)) or first_selectable_row_position(rows)
            print(
                f"reload-sync({self.helper_command(str(state_dir), 'list')})"
                f"+pos({position})+refresh-preview"
                f"+change-border-label( {dialogue_border_label(next_view)} )"
                f"+change-preview-label( {dialogue_preview_label(next_view, False)} )"
                f"+change-preview-window({dialogue_preview_window(False)})"
            )
            return 0

        if action in ("next-match", "prev-match"):
            current = int(extra[0]) if len(extra) > 0 and extra[0].isdigit() else 0
            fzf_query = extra[1] if len(extra) > 1 else ""
            fallback = "down" if action == "next-match" else "up"
            if read_state_mode(state_dir) != "dialogues" or fzf_query:
                print(fallback)
                return 0
            keyword = read_text(state_dir / "keyword")
            session_id = read_text(state_dir / "session_id")
            direction = 1 if action == "next-match" else -1
            if read_dialogue_view(state_dir) == "blocks":
                index = self.next_block_match_index(session_id, keyword, current, direction)
            else:
                index = self.next_match_index(session_id, keyword, current, direction)
            print(f"pos({index + 1})" if index is not None else fallback)
            return 0

        if action == "get-mode":
            print(read_state_mode(state_dir))
            return 0
        if action == "get-session":
            print(read_text(state_dir / "session_id"), end="")
            return 0
        if action == "get-cwd":
            print(read_text(state_dir / "cwd"), end="")
            return 0

        print(f"Unknown helper action: {action}", file=sys.stderr)
        return 1

    def rows_for_state(self, state_dir: Path) -> str:
        keyword = read_text(state_dir / "keyword")
        if read_state_mode(state_dir) == "dialogues":
            session_id = read_text(state_dir / "session_id")
            session = self.session_by_id(session_id)
            if session is None:
                return ""
            if read_dialogue_view(state_dir) == "blocks":
                rows = self.dialogue_block_rows(session, "")
            else:
                rows = self.dialogues_rows(session, "")
            return filter_rows_by_query(rows, keyword)
        return filter_rows_by_query(read_text(state_dir / "sessions.txt"), keyword)

    def run_fzf(self, state_dir: Path, include_all: bool) -> str:
        with_nth = "2,3"
        command = [
            "fzf",
            "--ansi",
            "--exact",
            "--cycle",
            "--no-sort",
            "--no-mouse",
            "--layout=reverse",
            "--disabled",
            "--border=rounded",
            "--border-label= Sessions ",
            "--border-label-pos=2",
            "--preview-label= Dialogues ",
            "--preview-label-pos=2",
            "--color=hl:black:yellow,hl+:black:yellow,preview-border:#b98cff,preview-label:#b98cff",
            "--header=↑↓ navigate │ → drill/focus preview │ F5 refresh │ ⇧Tab round/message │ ← back │ ^N/^F match │ ⏎ resume │ Esc",
            f"--bind=change:transform({self.helper_command(str(state_dir), 'search-transform', '{q}')})",
            f"--bind=up:transform({self.helper_command(str(state_dir), 'up-transform', '{1}', '{q}')})",
            f"--bind=down:transform({self.helper_command(str(state_dir), 'down-transform', '{1}', '{q}')})",
            f"--bind=shift-up:transform({self.helper_command(str(state_dir), 'page-up-transform', '{1}', '{q}')})",
            f"--bind=shift-down:transform({self.helper_command(str(state_dir), 'page-down-transform', '{1}', '{q}')})",
            f"--bind=right:transform({self.helper_command(str(state_dir), 'right-transform', '{1}', '{4}')})",
            f"--bind=left:transform({self.helper_command(str(state_dir), 'left-transform')})",
            f"--bind=shift-tab:transform({self.helper_command(str(state_dir), 'toggle-dialogue-view', '{1}')})",
            f"--bind=btab:transform({self.helper_command(str(state_dir), 'toggle-dialogue-view', '{1}')})",
            f"--bind=esc:transform({self.helper_command(str(state_dir), 'esc-transform')})",
            f"--bind=load:transform({self.helper_command(str(state_dir), 'load-jump')})",
            f"--bind=f5:transform({self.helper_command(str(state_dir), 'refresh-transform', '{1}', '{n}', '{q}')})",
            f"--bind=ctrl-n:transform({self.helper_command(str(state_dir), 'next-match', '{n}', '{q}')})",
            f"--bind=ctrl-f:transform({self.helper_command(str(state_dir), 'prev-match', '{n}', '{q}')})",
            f"--preview={self.helper_command(str(state_dir), 'preview', '{1}', '{q}')}",
            "--preview-window=right:60%:wrap:border-rounded",
            "--wrap-sign=",
            "--no-scrollbar",
            "--delimiter=\t",
            f"--with-nth={with_nth}",
        ]
        keyword = read_text(state_dir / "keyword")
        if keyword:
            command.append(f"--query={keyword}")
        helper_list = subprocess.check_output(
            [sys.executable, str(self.script_path), "--mode", self.mode, "--helper", "list", str(state_dir)],
            text=True,
        )
        result = subprocess.run(command, input=helper_list, text=True, capture_output=True)
        if result.returncode != 0:
            return ""
        return result.stdout.strip()


def blank_divider() -> str:
    return "\t".join(["__DIVIDER__", "", "", "", "", "", "", ""])


def row_with_hidden_search(key: int | str, label: str, searchable: str) -> str:
    return "\t".join([str(key), label, "", "", "", "", "", searchable])


def filter_rows_by_query(rows: str, query: str) -> str:
    if not query:
        return rows
    output: list[str] = []
    pending_dividers: list[str] = []
    for row in rows.splitlines():
        if not row:
            continue
        if row.startswith("__DIVIDER__"):
            pending_dividers.append(row)
            continue
        if row_matches_query(row, query):
            output.extend(pending_dividers)
            pending_dividers.clear()
            output.append(row)
    return "\n".join(output)


def row_matches_query(row: str, query: str) -> bool:
    haystack = "\t".join(row.split("\t")[1:]).casefold()
    return query.casefold() in haystack


def search_blob(*parts: object, max_chars: int = 20000) -> str:
    text = " ".join(str(part or "") for part in parts)
    cleaned = re.sub(r"\s+", " ", text.replace("\t", " ")).strip()
    return cleaned[:max_chars]


def session_search_blob(session: Session, dialogues: list[Dialogue]) -> str:
    return search_blob(
        session.id,
        session.title,
        session.cwd,
        session.provider,
        *(dialogue_search_blob(dialogue) for dialogue in dialogues),
        max_chars=500000,
    )


def dialogue_search_blob(dialogue: Dialogue) -> str:
    parts: list[str] = [dialogue.text]
    parts.extend(dialogue.tool_summaries)
    for plan in dialogue.plan_updates:
        parts.extend(step.step for step in plan.steps)
    for activity in dialogue.activities:
        if activity.text:
            parts.append(activity.text)
        if activity.plan_update is not None:
            parts.extend(step.step for step in activity.plan_update.steps)
    return search_blob(*parts)


def block_search_blob(block: DialogueBlock) -> str:
    return search_blob(*(dialogue_search_blob(dialogue) for dialogue in block.dialogues))


def dialogue_match_text(dialogue: Dialogue, needle: str) -> str:
    text = re.sub(r"\s+", " ", dialogue.text).strip()
    if needle.lower() in text.lower():
        return text
    return dialogue_search_blob(dialogue)


def first_selectable_row_position(rows: str) -> str:
    for index, row in enumerate(rows.splitlines(), start=1):
        if row and not row.startswith("__DIVIDER__"):
            return str(index)
    return "1"


def session_row_position(rows: str, session_id: str) -> str | None:
    if not session_id or session_id == "__DIVIDER__":
        return None
    return row_position(rows, session_id)


def row_position(rows: str, key: str) -> str | None:
    if not key:
        return None
    for index, row in enumerate(rows.splitlines(), start=1):
        if row.split("\t", 1)[0] == key:
            return str(index)
    return None


def dialogues_summary_preview(dialogues: list[Dialogue], cols: int) -> list[str]:
    sep_label = " Dialogues "
    sep_fill = max(0, cols - 2 - len(sep_label))
    lines = [f"{BOLD}{CYAN}──{sep_label}{'─' * sep_fill}{RESET}"]
    if not dialogues:
        lines.append(f"{DIM}  (no readable messages){RESET}")
        return lines
    num_width = len(str(dialogues[-1].num))
    prefix_cols = 1 + num_width + 2 + 2 + 1
    text_cols = max(20, cols - prefix_cols - 1)
    for dialogue in dialogues:
        text = one_line(dialogue.text, text_cols)
        icon = "👤" if dialogue.role == "user" else "🤖"
        color = CYAN if dialogue.role == "user" else YELLOW
        text_color = "" if dialogue.role == "user" else DIM
        lines.append(f" {color}{dialogue.num:>{num_width}}.{RESET} {icon} {text_color}{text}{RESET}")
    return lines


def search_dialogues_preview(dialogues: list[Dialogue], keyword: str, cols: int) -> list[str]:
    lines = [f"{MAGENTA}🔍 Keyword: {keyword}{RESET}", ""]
    needle = keyword.lower()
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    hits = [dialogue for dialogue in dialogues if needle in dialogue_search_blob(dialogue).lower()]
    if not hits:
        lines.append(f"{DIM}  (no matches in user/assistant messages){RESET}")
        return lines

    sep_label = f" Matched dialogues ({len(hits)}) "
    sep_fill = max(0, cols - 2 - len(sep_label))
    lines.append(f"{BOLD}{CYAN}──{sep_label}{'─' * sep_fill}{RESET}")
    num_width = len(str(dialogues[-1].num)) if dialogues else 1
    for dialogue in hits[:15]:
        text = dialogue_match_text(dialogue, needle)
        match = pattern.search(text)
        if match:
            start = max(0, match.start() - 30)
            text = ("…" if start > 0 else "") + text[start:]
        text = visual_truncate(text, max(20, cols - 8 - num_width))
        text = pattern.sub(lambda item: f"{HIGHLIGHT}{item.group()}{RESET}", text)
        icon = "👤" if dialogue.role == "user" else "🤖"
        color = CYAN if dialogue.role == "user" else YELLOW
        lines.append(f" {color}{dialogue.num:>{num_width}}.{RESET} {icon} {text}")
    if len(hits) > 15:
        lines.append(f"{DIM}  ··· {len(hits) - 15} more matches ···{RESET}")
    return lines


def highlight_rendered_lines(lines: list[str], highlight: str) -> list[str]:
    return [highlight_matches(line, highlight) for line in lines]


def print_preview_lines(lines: list[str], offset: int = 0) -> None:
    if not lines:
        return
    start = min(max(0, offset), max(0, len(lines) - 1))
    print("\n".join(lines[start:]))


def initial_keyword_offset(lines: list[str], keyword: str, height: int) -> int:
    if not keyword:
        return 0
    needle = keyword.casefold()
    for index, line in enumerate(lines):
        if index < 5:
            continue
        if needle in ANSI_RE.sub("", line).casefold():
            return max(0, index - preview_context_lines(height))
    return 0


def preview_context_lines(height: int) -> int:
    return max(2, min(6, max(1, height) // 5))


def preview_page_offset(lines: list[str], offset: int, height: int, cols: int, direction: int) -> int:
    if not lines:
        return 0
    starts = display_line_starts(lines, cols)
    anchors = message_scroll_anchors(lines, starts)
    return cached_preview_page_offset(len(lines), starts, anchors, offset, height, direction)


def cached_preview_page_offset(
    line_count: int,
    starts: list[int],
    anchors: list[tuple[int, int, int]],
    offset: int,
    height: int,
    direction: int,
) -> int:
    if line_count <= 0:
        return 0
    max_offset = line_count - 1
    offset = min(max(0, offset), max_offset)
    if not starts:
        return 0
    if len(starts) < line_count:
        starts = starts + [starts[-1]] * (line_count - len(starts))
    current_display = starts[offset]
    if direction > 0:
        bottom_display = current_display + max(1, height) - 1
        candidates = [
            raw_index
            for raw_index, _start_display, content_display in anchors
            if raw_index > offset and content_display <= bottom_display
        ]
        if candidates:
            return candidates[-1]
        next_offset = raw_index_at_display(starts, current_display + max(1, height - 4))
        return next_offset if next_offset > offset else min(max_offset, offset + 1)
    target_display = max(0, current_display - max(1, height - 4))
    candidates = [raw_index for raw_index, start_display, _content_display in anchors if start_display <= target_display]
    if candidates:
        return candidates[-1]
    next_offset = raw_index_at_display(starts, target_display)
    return next_offset if next_offset < offset else max(0, offset - 1)


def display_line_starts(lines: list[str], cols: int) -> list[int]:
    starts: list[int] = []
    current = 0
    width = max(20, cols)
    for line in lines:
        starts.append(current)
        current += display_line_count(line, width)
    return starts


def display_line_count(line: str, cols: int) -> int:
    plain = ANSI_RE.sub("", line)
    return max(1, (visual_text_width(plain) + cols - 1) // cols)


def raw_index_at_display(starts: list[int], target_display: int) -> int:
    index = 0
    for position, start_display in enumerate(starts):
        if start_display > target_display:
            break
        index = position
    return index


def message_scroll_anchors(lines: list[str], starts: list[int]) -> list[tuple[int, int, int]]:
    anchors: list[tuple[int, int, int]] = []
    for index, line in enumerate(lines):
        plain = ANSI_RE.sub("", line).lstrip()
        if plain.startswith("┄") and " message " in plain:
            content_index = min(index + 1, len(lines) - 1)
            anchors.append((index, starts[index], starts[content_index]))
        elif plain.startswith("──") and "· message " in plain and "· messages " not in plain:
            content_index = min(index + 1, len(lines) - 1)
            anchors.append((index, starts[index], starts[content_index]))
    return anchors


def role_group_divider(group: list[Dialogue], assistant_label: str, cols: int) -> str:
    role_label = "User" if group[0].role == "user" else assistant_label
    icon = "👤" if group[0].role == "user" else "🤖"
    color = CYAN if group[0].role == "user" else YELLOW
    message_label = message_range_label(group)
    prefix = f"── {icon} {role_label} · {message_label} "
    fill = max(8, cols - visual_text_width(prefix) - 2)
    return f"{BOLD}{color}{prefix}{'─' * fill}{RESET}"


def message_range_label(group: list[Dialogue]) -> str:
    first = group[0].num
    last = group[-1].num
    return f"message {first}" if first == last else f"messages {first}-{last}"


def preview_message_range_label(first: int, last: int, total: int) -> str:
    if first == last:
        return f"message {first} of {total}"
    return f"messages {first}-{last} of {total}"


def message_divider(num: int, cols: int) -> str:
    label = f"┄┄┄┄┄ message {num} "
    fill = max(12, min(48, cols - visual_text_width(label) - 2))
    return f"{DIM}{label}{'┄' * fill}{RESET}"


def interrupt_divider(cols: int) -> str:
    label = "── user interrupted "
    fill = max(8, cols - visual_text_width(label) - 2)
    return f"{INTERRUPT}{label}{'─' * fill}{RESET}"


def tool_summary_lines(dialogue: Dialogue, cols: int, limit: int = 2) -> list[str]:
    return tool_summary_list_lines(dialogue.tool_summaries, cols, limit)


def tool_summary_list_lines(summaries: tuple[str, ...] | list[str], cols: int, limit: int = 2) -> list[str]:
    lines: list[str] = []
    shown = tuple(summaries[:limit])
    for summary in shown:
        label = f"↳ tool: {summary}"
        lines.append(f"{DIM}{visual_truncate(label, max(20, cols - 2))}{RESET}")
    remaining = len(summaries) - len(shown)
    if remaining > 0:
        lines.append(f"{DIM}↳ … +{remaining} more tools{RESET}")
    return lines


def dialogue_activity_lines(dialogue: Dialogue, cols: int) -> list[str]:
    if not dialogue.activities:
        lines = plan_update_lines(dialogue, cols)
        tool_lines = tool_summary_lines(dialogue, cols)
        if lines and tool_lines:
            lines.append("")
            lines.extend(tool_lines)
        elif tool_lines:
            lines = tool_lines
        return lines

    lines: list[str] = []
    pending_tools: list[str] = []

    def flush_tools() -> None:
        if not pending_tools:
            return
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(tool_summary_list_lines(pending_tools, cols))
        pending_tools.clear()

    for activity in dialogue.activities:
        if activity.kind == "tool":
            if activity.text:
                pending_tools.append(activity.text)
            continue
        if activity.kind == "plan" and activity.plan_update is not None:
            flush_tools()
            if lines:
                lines.append("")
            lines.extend(render_plan_update(activity.plan_update, cols))
    flush_tools()
    return lines


def plan_update_lines(dialogue: Dialogue, cols: int) -> list[str]:
    lines: list[str] = []
    for index, plan in enumerate(dialogue.plan_updates):
        if index:
            lines.append("")
        lines.extend(render_plan_update(plan, cols))
    return lines


def render_plan_update(plan: PlanUpdate, cols: int) -> list[str]:
    lines = [f"{DIM}• {BOLD}Updated Plan{RESET}"]
    for index, step in enumerate(plan.steps):
        lines.extend(plan_step_lines(step.status, step.step, cols, first=index == 0))
    return lines


def plan_step_marker_and_style(status: str) -> tuple[str, str, str]:
    normalized = status.strip().lower().replace("-", "_")
    if normalized == "completed":
        return "✓", DIM, f"{DIM}{STRIKE}"
    return "□", PLAN_ACTIVE, f"{PLAN_ACTIVE}{BOLD}"


def plan_step_lines(status: str, text: str, cols: int, first: bool = False) -> list[str]:
    marker, marker_style, text_style = plan_step_marker_and_style(status)
    prefix = f"↳ {marker} " if first else f"  {marker} "
    return styled_wrapped_lines(prefix, text, cols, text_style, marker_style)


def styled_wrapped_lines(prefix: str, text: str, cols: int, text_style: str, prefix_style: str | None = None) -> list[str]:
    prefix_style = text_style if prefix_style is None else prefix_style
    text_cols = max(12, cols - visual_text_width(prefix) - 2)
    rendered: list[str] = []
    for index, segment in enumerate(wrap_visual(text, text_cols)):
        line_prefix = prefix if index == 0 else " " * visual_text_width(prefix)
        rendered.append(f"{prefix_style}{line_prefix}{RESET}{text_style}{segment}{RESET}")
    return rendered


def quoted_command(*parts: str) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def read_state_mode(state_dir: Path) -> str:
    try:
        return (state_dir / "mode").read_text(encoding="utf-8")
    except OSError:
        return "sessions"


def read_state_focus(state_dir: Path) -> str:
    try:
        return (state_dir / "focus").read_text(encoding="utf-8")
    except OSError:
        return "list"


def read_dialogue_view(state_dir: Path) -> str:
    view = read_text(state_dir / "dialogue_view")
    return "blocks" if view == "blocks" else "messages"


def preview_state_key(state_dir: Path, row_num: str, keyword: str) -> str:
    return "\t".join([read_text(state_dir / "session_id"), read_dialogue_view(state_dir), row_num, keyword])


def preview_cache_paths(state_dir: Path) -> tuple[Path, Path, Path]:
    return state_dir / "preview_cache_key", state_dir / "preview_cache.txt", state_dir / "preview_cache_meta.json"


def write_preview_cache(state_dir: Path, key: str, lines: list[str], cols: int) -> None:
    cache_key, cache_text, cache_meta = preview_cache_paths(state_dir)
    starts = display_line_starts(lines, cols)
    anchors = message_scroll_anchors(lines, starts)
    meta = {
        "cols": cols,
        "line_count": len(lines),
        "starts": starts,
        "anchors": anchors,
    }
    write_text(cache_key, key)
    write_text(cache_text, "\n".join(lines))
    write_text(cache_meta, json.dumps(meta, separators=(",", ":")))


def read_preview_cache(
    state_dir: Path,
    key: str,
    cols: int,
) -> tuple[list[str], list[int], list[tuple[int, int, int]]] | None:
    cache_key, cache_text, cache_meta = preview_cache_paths(state_dir)
    if read_text(cache_key) != key or not cache_text.exists() or not cache_meta.exists():
        return None
    try:
        meta = json.loads(cache_meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if meta.get("cols") != cols:
        return None
    try:
        lines = cache_text.read_text(encoding="utf-8").split("\n")
        starts = [int(value) for value in meta.get("starts", [])]
        anchors = [tuple(int(value) for value in anchor) for anchor in meta.get("anchors", [])]
    except (OSError, TypeError, ValueError):
        return None
    if len(starts) != len(lines):
        return None
    if any(len(anchor) != 3 for anchor in anchors):
        return None
    return lines, starts, anchors


def read_preview_offset(state_dir: Path, key: str) -> int:
    if read_text(state_dir / "preview_key") != key:
        write_preview_offset(state_dir, key, 0)
        return 0
    value = read_text(state_dir / "preview_offset")
    return int(value) if value.isdigit() else 0


def write_preview_offset(state_dir: Path, key: str, offset: int) -> None:
    write_text(state_dir / "preview_key", key)
    write_text(state_dir / "preview_offset", str(max(0, offset)))


def reset_preview_scroll(state_dir: Path) -> None:
    for name in ("preview_offset", "preview_key", "preview_cache_key", "preview_cache.txt", "preview_cache_meta.json"):
        unlink_if_exists(state_dir / name)


def dialogue_border_label(view: str) -> str:
    return "Rounds" if view == "blocks" else "Dialogues"


def dialogue_preview_label(view: str, focused: bool) -> str:
    label = "Round" if view == "blocks" else "Content"
    if focused:
        return f"▶ {label} · ↑↓ scroll · ⇧↑/⇧↓ page · F5 refresh · ← back"
    return label


def dialogue_preview_window(focused: bool) -> str:
    return "right:60%:wrap:border-bold" if focused else "right:60%:wrap:border-rounded"


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
