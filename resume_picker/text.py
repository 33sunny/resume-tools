from __future__ import annotations

import os
import re
import shutil
import unicodedata
from datetime import datetime, timedelta

from .models import parse_iso


RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
WHITE = "\033[1;37m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
MAGENTA = "\033[1;35m"
HIGHLIGHT = "\033[1;43;30m"
INLINE_CODE_OPEN = "\033[38;2;203;166;247m"
INLINE_CODE_CLOSE = "\033[39m"
BOLD_CLOSE = "\033[22m"

INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
WEEKDAYS_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def visual_width(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1


def visual_text_width(text: str) -> int:
    return sum(visual_width(char) for char in text)


def visual_truncate(text: str, max_cols: int) -> str:
    if max_cols <= 1:
        return "..."
    out: list[str] = []
    used = 0
    for char in text:
        width = visual_width(char)
        if used + width > max_cols - 1:
            out.append("…")
            return "".join(out)
        out.append(char)
        used += width
    return "".join(out)


def one_line(text: str, max_cols: int = 90) -> str:
    return visual_truncate(re.sub(r"\s+", " ", text.replace("\t", " ")).strip(), max_cols)


def normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def terminal_list_cols() -> int:
    columns = shutil.get_terminal_size((120, 24)).columns
    try:
        with open("/dev/tty") as tty:
            columns = os.get_terminal_size(tty.fileno()).columns
    except OSError:
        pass
    return max(44, min(160, int(columns * 0.4) - 4))


def full_width_divider(label: str) -> str:
    width = terminal_list_cols()
    label_text = f" {label} "
    label_cols = visual_text_width(label_text)
    side_cols = max(8, (width - label_cols) // 2)
    left = "─" * side_cols
    right = "─" * max(8, width - side_cols - label_cols)
    return f"{left}{label_text}{right}"


def compact_divider(label: str) -> str:
    line = f"─── {label} ───"
    pad = max(0, (terminal_list_cols() - visual_text_width(line)) // 2)
    return (" " * pad) + line


def format_time(value: str) -> str:
    parsed = parse_iso(value)
    if parsed is None:
        return value[:16] if value else "-"
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def format_row_time(value: str) -> str:
    parsed = parse_iso(value)
    if parsed is None:
        return value[11:16] if len(value) >= 16 else "-"
    return parsed.astimezone().strftime("%H:%M")


def format_date_label(value: str, now: datetime | None = None) -> str:
    parsed = parse_iso(value)
    if parsed is None:
        return value[:10] if value else "-"
    local = parsed.astimezone()
    today = (now or datetime.now().astimezone()).date()
    if local.date() == today:
        return f"{local:%Y-%m-%d}  今天"
    if local.date() == today - timedelta(days=1):
        return f"{local:%Y-%m-%d}  昨天"
    return f"{local:%Y-%m-%d}  {WEEKDAYS_CN[local.weekday()]}"


def week_start(value: datetime) -> datetime:
    local = value.astimezone()
    return local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=local.weekday())


def month_week_number(value: datetime) -> int:
    local = value.astimezone()
    first_day = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    first_week_start = week_start(first_day)
    return ((local.date() - first_week_start.date()).days // 7) + 1


def chinese_ordinal(value: int) -> str:
    names = ["零", "一", "二", "三", "四", "五", "六"]
    return names[value] if 0 <= value < len(names) else str(value)


def week_label(value: str, now: datetime) -> str:
    parsed = parse_iso(value)
    if parsed is None:
        return "时间未知"
    local = parsed.astimezone()
    current_week = week_start(now)
    session_week = week_start(local)
    if session_week.date() == current_week.date():
        return "本周"
    if session_week.date() == (current_week - timedelta(days=7)).date():
        return "上周"
    return f"{local.month}月·第{chinese_ordinal(month_week_number(local))}周"


def highlight_matches(text: str, needle: str) -> str:
    if not needle:
        return text
    pattern = re.compile(re.escape(needle), re.IGNORECASE)
    return pattern.sub(lambda match: f"{HIGHLIGHT}{match.group()}{RESET}", text)


def render_markdown(text: str) -> str:
    text = BOLD_RE.sub(lambda match: f"{BOLD}{match.group(1)}{BOLD_CLOSE}", text)
    return INLINE_CODE_RE.sub(lambda match: f"{INLINE_CODE_OPEN}{match.group(1)}{INLINE_CODE_CLOSE}", text)
