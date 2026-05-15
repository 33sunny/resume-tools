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
FILE_LINK_OPEN = "\033[38;2;142;236;211m"
FILE_LINK_CLOSE = "\033[39m"
QUOTE_BAR = "\033[38;2;137;180;250m▌\033[0m"
QUOTE_TEXT_OPEN = "\033[2m"
BOLD_CLOSE = "\033[22m"
CODE_BLOCK_BG = "\033[48;2;31;33;38m"
CODE_BLOCK_FG = "\033[38;2;216;216;216m"

ANSI_RE = re.compile(r"\033\[([0-9;:]*)m")
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
FENCE_RE = re.compile(r"^\s*```\s*([A-Za-z0-9_-]+)?\s*$")
LOCAL_FILE_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(((?:/|~)[^)\n]+)\)")
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
    return pattern.sub(lambda match: f"{HIGHLIGHT}{match.group()}{RESET}{active_sgr_at(text, match.start())}", text)


def active_sgr_at(text: str, position: int) -> str:
    active: list[str] = []
    for match in ANSI_RE.finditer(text[:position]):
        params = match.group(1) or "0"
        if params == "0":
            active.clear()
            continue
        remove_sgr(active, params)
        active.append(f"\033[{params}m")
    return "".join(active)


def remove_sgr(active: list[str], params: str) -> None:
    codes = params.split(";")
    if "22" in codes:
        active[:] = [item for item in active if item not in (BOLD, DIM)]
    if "39" in codes:
        active[:] = [item for item in active if not is_foreground_sgr(item)]
    if "49" in codes:
        active[:] = [item for item in active if not is_background_sgr(item)]


def is_foreground_sgr(sequence: str) -> bool:
    if not sequence.startswith("\033[") or not sequence.endswith("m"):
        return False
    params = sequence[2:-1].split(";")
    return any(code in params for code in ("30", "31", "32", "33", "34", "35", "36", "37", "38", "39", "90", "91", "92", "93", "94", "95", "96", "97"))


def is_background_sgr(sequence: str) -> bool:
    if not sequence.startswith("\033[") or not sequence.endswith("m"):
        return False
    params = sequence[2:-1].split(";")
    return any(code in params for code in ("40", "41", "42", "43", "44", "45", "46", "47", "48", "49", "100", "101", "102", "103", "104", "105", "106", "107"))


def render_markdown(text: str) -> str:
    text = BOLD_RE.sub(lambda match: f"{BOLD}{match.group(1)}{BOLD_CLOSE}", text)
    return INLINE_CODE_RE.sub(lambda match: f"{INLINE_CODE_OPEN}{match.group(1)}{INLINE_CODE_CLOSE}", text)


def render_markdown_text_line(text: str) -> list[str]:
    paths: list[str] = []

    def replace_file_link(match: re.Match[str]) -> str:
        paths.append(match.group(2))
        return f"{FILE_LINK_OPEN}{match.group(1)}{FILE_LINK_CLOSE}"

    rendered = render_markdown(LOCAL_FILE_LINK_RE.sub(replace_file_link, text))
    if not paths:
        return [rendered]
    path_indent = file_link_path_indent(text)
    return [rendered, *[f"{DIM}{path_indent}{path}{RESET}" for path in paths]]


def render_quote_line(text: str, cols: int) -> list[str]:
    width = max(8, cols - visual_text_width("▌ "))
    rendered: list[str] = []
    for wrapped_line in wrap_visual(text, width):
        rendered.extend(render_markdown_text_line(wrapped_line))
    return [quote_prefix_line(line) for line in rendered]


def quote_prefix_line(line: str) -> str:
    return f"{QUOTE_BAR} {QUOTE_TEXT_OPEN}{line}{RESET}" if line else QUOTE_BAR


def file_link_path_indent(text: str) -> str:
    leading = text[: len(text) - len(text.lstrip(" "))]
    return f"{leading}  " if text.lstrip().startswith(("-", "*", "+")) else leading


def render_markdown_lines(text: str, cols: int) -> list[str]:
    lines: list[str] = []
    code_lines: list[str] = []
    code_lang = ""
    in_code = False
    for raw_line in text.splitlines():
        quote = quote_text(raw_line)
        if quote is not None:
            if in_code:
                code_lines.append(raw_line)
            else:
                lines.extend(render_quote_line(quote, cols))
            continue
        fence = FENCE_RE.match(raw_line)
        if fence:
            if in_code:
                lines.extend(render_code_block(code_lines, code_lang, cols))
                code_lines = []
                code_lang = ""
                in_code = False
            else:
                in_code = True
                code_lang = (fence.group(1) or "").strip().lower()
            continue
        if in_code:
            code_lines.append(raw_line)
        else:
            lines.extend(render_markdown_text_line(raw_line))
    if in_code:
        lines.extend(render_code_block(code_lines, code_lang, cols))
    return lines


def quote_text(line: str) -> str | None:
    match = re.match(r"^\s*>\s?(.*)$", line)
    return match.group(1) if match else None


def render_code_block(lines: list[str], lang: str, cols: int) -> list[str]:
    width = max(24, cols - 6)
    rendered = ["", code_block_line("", width)]
    if not lines:
        lines = [""]
    for line in dedent_code_lines(lines):
        for wrapped_line in wrap_visual(line, max(8, width - 4)):
            rendered.append(code_block_line(wrapped_line, width))
    rendered.extend([code_block_line("", width), ""])
    return rendered


def dedent_code_lines(lines: list[str]) -> list[str]:
    indents = [len(line) - len(line.lstrip(" ")) for line in lines if line.strip()]
    if not indents:
        return lines
    indent = min(indents)
    return [line[indent:] if len(line) >= indent else line for line in lines]


def code_block_line(text: str, cols: int) -> str:
    return f"  {CODE_BLOCK_BG}{CODE_BLOCK_FG}{pad_visual('  ' + text, cols)}{RESET}"


def wrap_visual(text: str, max_cols: int) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    remaining = text
    while visual_text_width(remaining) > max_cols:
        used = 0
        break_index = 0
        last_space = -1
        for index, char in enumerate(remaining):
            width = visual_width(char)
            if used + width > max_cols:
                break
            used += width
            break_index = index + 1
            if char.isspace():
                last_space = index
        if use_space_break(last_space, max_cols, remaining):
            lines.append(remaining[:last_space].rstrip())
            remaining = remaining[last_space + 1 :].lstrip()
        else:
            lines.append(remaining[:break_index].rstrip())
            remaining = remaining[break_index:]
    lines.append(remaining.rstrip())
    return lines


def use_space_break(last_space: int, max_cols: int, text: str) -> bool:
    if last_space <= 0:
        return False
    before = text[:last_space].rstrip()
    return visual_text_width(before) >= min(max(8, max_cols // 4), max_cols - 1)


def pad_visual(text: str, cols: int) -> str:
    return text + (" " * max(0, cols - visual_text_width(text)))
