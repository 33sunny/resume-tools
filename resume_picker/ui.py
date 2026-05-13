from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import Dialogue, ProviderConfig, Session
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
    render_markdown,
    visual_truncate,
    week_label,
)


class Provider(Protocol):
    config: ProviderConfig

    def load_sessions(self) -> list[Session]:
        ...

    def parse_dialogues(self, session: Session) -> list[Dialogue]:
        ...


def preview_cols() -> int:
    value = os.environ.get("FZF_PREVIEW_COLUMNS", "")
    return int(value) if value.isdigit() else 100


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
            if any(needle in dialogue.text.lower() for dialogue in self.provider.parse_dialogues(session)):
                result.append(session)
        return result

    def message_count(self, session: Session) -> int:
        return len(self.provider.parse_dialogues(session))

    def session_row(self, session: Session) -> str:
        title_prefix = "★ " if session.renamed else "  "
        return "\t".join(
            [
                session.id,
                format_row_time(session.updated_at),
                f"{title_prefix}{session.title}",
                session.cwd,
                f"{self.message_count(session)} dialogues",
                f"[{session.id[:8]}]",
                session.provider,
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
                rows.append(f"__DIVIDER__\t{BOLD}{DIM}{full_width_divider(week)}{RESET}\t\t\t\t\t")
            day = format_date_label(timestamp, now)
            if day != current_day:
                current_day = day
                rows.append(f"__DIVIDER__\t{BOLD}{DIM}{compact_divider(day)}{RESET}\t\t\t\t\t")
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
            rows.append(f"{dialogue.num}\t{label}")
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
            f"{DIM}📅 {format_time(session.updated_at)}  •  {len(dialogues)} dialogues  •  {session.provider}{RESET}",
            f"{DIM}ID {session.id}{RESET}",
            "",
        ]
        if keyword:
            lines.extend(search_dialogues_preview(dialogues, keyword, cols))
        else:
            lines.extend(dialogues_summary_preview(dialogues, cols))
        print("\n".join(lines))
        return 0

    def dialogue_preview(self, session_id: str, num: int, highlight: str = "") -> int:
        session = self.session_by_id(session_id)
        if session is None:
            print(f"Session not found: {session_id}")
            return 1
        dialogues = self.provider.parse_dialogues(session)
        target = next((dialogue for dialogue in dialogues if dialogue.num == num), None)
        if target is None:
            print(f"Message {num} not found.")
            return 1

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
            highlight_matches(render_markdown(target.text), highlight),
        ]
        print("\n".join(lines))
        return 0

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

    def helper_command(self, state_dir: str, *args: str) -> str:
        return quoted_command(sys.executable, str(self.script_path), "--mode", self.mode, "--helper", *args[:1], state_dir, *args[1:])

    def helper_main(self, state_dir: Path, action: str, extra: list[str]) -> int:
        if action == "list":
            if read_state_mode(state_dir) == "dialogues":
                session_id = read_text(state_dir / "session_id")
                keyword = read_text(state_dir / "keyword")
                session = self.session_by_id(session_id)
                if session:
                    print(self.dialogues_rows(session, keyword))
            else:
                print(read_text(state_dir / "sessions.txt"), end="")
            return 0

        if action == "preview":
            field1 = extra[0] if len(extra) > 0 else ""
            fzf_query = extra[1] if len(extra) > 1 else ""
            if not field1 or field1 == "__DIVIDER__":
                return 0
            if read_state_mode(state_dir) == "dialogues":
                session_id = read_text(state_dir / "session_id")
                keyword = fzf_query or read_text(state_dir / "keyword")
                return self.dialogue_preview(session_id, int(field1), keyword)
            keyword = read_text(state_dir / "keyword")
            return self.session_preview(field1, keyword)

        if action == "up-transform":
            print("preview-up" if read_state_mode(state_dir) == "dialogues" and read_state_focus(state_dir) == "preview" else "up")
            return 0

        if action == "down-transform":
            print("preview-down" if read_state_mode(state_dir) == "dialogues" and read_state_focus(state_dir) == "preview" else "down")
            return 0

        if action == "right-transform":
            session_id = extra[0] if len(extra) > 0 else ""
            cwd = extra[1] if len(extra) > 1 else ""
            if read_state_mode(state_dir) == "dialogues":
                if read_state_focus(state_dir) != "preview":
                    write_text(state_dir / "focus", "preview")
                    print("change-preview-label( ▶ Content · ↑↓ scroll · ← back )")
                return 0
            if not session_id or session_id == "__DIVIDER__":
                return 0
            write_text(state_dir / "mode", "dialogues")
            write_text(state_dir / "focus", "list")
            write_text(state_dir / "session_id", session_id)
            write_text(state_dir / "cwd", cwd)
            unlink_if_exists(state_dir / "load_jump")
            keyword = read_text(state_dir / "keyword")
            if keyword:
                index = self.next_match_index(session_id, keyword, -1, 1)
                if index is not None:
                    write_text(state_dir / "load_jump", str(index + 1))
            print(
                f"reload-sync({self.helper_command(str(state_dir), 'list')})"
                "+first+refresh-preview+change-border-label( Dialogues )+change-preview-label( Content )"
            )
            return 0

        if action == "left-transform":
            if read_state_mode(state_dir) == "dialogues" and read_state_focus(state_dir) == "preview":
                write_text(state_dir / "focus", "list")
                print("change-preview-label( Content )")
                return 0
            if read_state_mode(state_dir) == "sessions":
                return 0
            write_text(state_dir / "mode", "sessions")
            write_text(state_dir / "focus", "list")
            for name in ("session_id", "cwd", "load_jump"):
                unlink_if_exists(state_dir / name)
            print(
                f"reload-sync({self.helper_command(str(state_dir), 'list')})"
                "+first+refresh-preview+change-border-label( Sessions )+change-preview-label( Dialogues )"
            )
            return 0

        if action == "esc-transform":
            if read_state_mode(state_dir) == "dialogues" and read_state_focus(state_dir) == "preview":
                write_text(state_dir / "focus", "list")
                print("change-preview-label( Content )")
                return 0
            if read_state_mode(state_dir) == "dialogues":
                write_text(state_dir / "mode", "sessions")
                write_text(state_dir / "focus", "list")
                for name in ("session_id", "cwd", "load_jump"):
                    unlink_if_exists(state_dir / name)
                print(
                    f"reload-sync({self.helper_command(str(state_dir), 'list')})"
                    "+first+refresh-preview+change-border-label( Sessions )+change-preview-label( Dialogues )"
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

    def run_fzf(self, state_dir: Path, include_all: bool) -> str:
        with_nth = "2..7" if include_all else "2,3,5,6,7"
        command = [
            "fzf",
            "--ansi",
            "--exact",
            "--cycle",
            "--no-sort",
            "--no-mouse",
            "--layout=reverse",
            "--border=rounded",
            "--border-label= Sessions ",
            "--border-label-pos=2",
            "--preview-label= Dialogues ",
            "--preview-label-pos=2",
            "--color=hl:black:yellow,hl+:black:yellow",
            "--header=↑↓ navigate │ → drill / focus preview │ ← back │ ^N/^F next/prev match │ ⏎ resume │ Esc quit/back",
            f"--bind=up:transform({self.helper_command(str(state_dir), 'up-transform')})",
            f"--bind=down:transform({self.helper_command(str(state_dir), 'down-transform')})",
            f"--bind=right:transform({self.helper_command(str(state_dir), 'right-transform', '{1}', '{4}')})",
            f"--bind=left:transform({self.helper_command(str(state_dir), 'left-transform')})",
            f"--bind=esc:transform({self.helper_command(str(state_dir), 'esc-transform')})",
            f"--bind=load:transform({self.helper_command(str(state_dir), 'load-jump')})",
            f"--bind=ctrl-n:transform({self.helper_command(str(state_dir), 'next-match', '{n}', '{q}')})",
            f"--bind=ctrl-f:transform({self.helper_command(str(state_dir), 'prev-match', '{n}', '{q}')})",
            f"--preview={self.helper_command(str(state_dir), 'preview', '{1}', '{q}')}",
            "--preview-window=right:60%:wrap:border-rounded",
            "--delimiter=\t",
            f"--with-nth={with_nth}",
            "--nth=1,2",
        ]
        helper_list = subprocess.check_output(
            [sys.executable, str(self.script_path), "--mode", self.mode, "--helper", "list", str(state_dir)],
            text=True,
        )
        result = subprocess.run(command, input=helper_list, text=True, capture_output=True)
        if result.returncode != 0:
            return ""
        return result.stdout.strip()


def blank_divider() -> str:
    return "\t".join(["__DIVIDER__", "", "", "", "", "", ""])


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
    hits = [dialogue for dialogue in dialogues if needle in dialogue.text.lower()]
    if not hits:
        lines.append(f"{DIM}  (no matches in user/assistant messages){RESET}")
        return lines

    sep_label = f" Matched dialogues ({len(hits)}) "
    sep_fill = max(0, cols - 2 - len(sep_label))
    lines.append(f"{BOLD}{CYAN}──{sep_label}{'─' * sep_fill}{RESET}")
    num_width = len(str(dialogues[-1].num)) if dialogues else 1
    for dialogue in hits[:15]:
        text = re.sub(r"\s+", " ", dialogue.text).strip()
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
