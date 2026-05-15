from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

from .providers.claude import ClaudeProvider
from .providers.codex import CodexProvider
from .ui import Picker, filter_rows_by_query, first_selectable_row_position, read_state_mode, read_text, write_text


def mode_from_argv(argv0: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    name = Path(argv0).name
    if name == "claude-resume":
        return "claude"
    if name == "codex-resume":
        return "codex"
    return "proxy"


def make_provider(mode: str):
    if mode == "claude":
        return ClaudeProvider()
    if mode in ("codex", "proxy"):
        return CodexProvider(mode)
    raise ValueError(f"Unknown mode: {mode}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    early_mode = ""
    for index, arg in enumerate(argv):
        if arg == "--mode" and index + 1 < len(argv):
            early_mode = argv[index + 1]
            break
        if arg.startswith("--mode="):
            early_mode = arg.split("=", 1)[1]
            break
    mode = mode_from_argv(sys.argv[0], early_mode)
    provider = make_provider(mode)
    picker = Picker(provider, Path(sys.argv[0]).resolve(), mode)
    config = provider.config

    parser = argparse.ArgumentParser(description=f"Pick a {config.session_label} session and resume it.")
    parser.add_argument("--mode", choices=("claude", "codex", "proxy"), default=mode, help=argparse.SUPPRESS)
    parser.add_argument("-a", "-s", "--search", "--all", dest="all", action="store_true", help="show all directories; optionally full-text search")
    parser.add_argument("--keyword", default="", help="non-interactive keyword for --all/--search")
    parser.add_argument("--list", action="store_true", help="print candidate sessions without opening fzf")
    parser.add_argument("--preview", metavar="SESSION_ID", help="print session-level dialogue preview")
    parser.add_argument("--dialogues", metavar="SESSION_ID", help="print dialogue list for one session")
    parser.add_argument("--rounds", "--blocks", dest="blocks", metavar="SESSION_ID", help="print dialogue round list for one session")
    parser.add_argument("--message-preview", nargs=2, metavar=("SESSION_ID", "NUM"), help="print one dialogue message")
    parser.add_argument(
        "--round-preview",
        "--block-preview",
        dest="block_preview",
        nargs=2,
        metavar=("SESSION_ID", "NUM"),
        help="print one dialogue round",
    )
    parser.add_argument("--helper", nargs=2, metavar=("ACTION", "STATE_DIR"), help=argparse.SUPPRESS)
    parser.add_argument("extra", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.mode != mode:
        mode = args.mode
        provider = make_provider(mode)
        picker = Picker(provider, Path(sys.argv[0]).resolve(), mode)
        config = provider.config

    if args.helper:
        action, state_dir = args.helper
        return picker.helper_main(Path(state_dir), action, args.extra)
    if args.preview:
        return picker.session_preview(args.preview, args.keyword)
    if args.dialogues:
        session = picker.session_by_id(args.dialogues)
        if not session:
            print(f"Session not found: {args.dialogues}", file=sys.stderr)
            return 1
        print(picker.dialogues_rows(session, args.keyword))
        return 0
    if args.blocks:
        session = picker.session_by_id(args.blocks)
        if not session:
            print(f"Session not found: {args.blocks}", file=sys.stderr)
            return 1
        print(picker.dialogue_block_rows(session, args.keyword))
        return 0
    if args.message_preview:
        return picker.dialogue_preview(args.message_preview[0], int(args.message_preview[1]), args.keyword)
    if args.block_preview:
        return picker.dialogue_block_preview(args.block_preview[0], int(args.block_preview[1]), args.keyword)

    include_all = args.all
    keyword = args.keyword
    if include_all and not keyword and not args.list and sys.stdin.isatty():
        print("Search keyword (Enter to show all): ", end="", flush=True)
        keyword = sys.stdin.readline().rstrip("\n")

    sessions = picker.filter_sessions(os.getcwd(), include_all, keyword if args.list else "")
    rows = picker.session_rows(sessions)

    if args.list:
        if rows:
            print(rows)
        return 0

    visible_rows = filter_rows_by_query(rows, keyword)
    if not visible_rows:
        scope = "all directories" if include_all else os.getcwd()
        print(f"No {config.session_label} sessions found for {scope}.")
        return 0

    if not shutil.which("fzf"):
        print(f"fzf is required. Install it or run {config.resume_command} resume <session_id> directly.", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix=config.temp_prefix) as state:
        state_dir = Path(state)
        write_text(state_dir / "mode", "sessions")
        write_text(state_dir / "focus", "list")
        write_text(state_dir / "sessions.txt", rows)
        write_text(state_dir / "keyword", keyword)
        write_text(state_dir / "load_jump", first_selectable_row_position(visible_rows))
        write_text(state_dir / "scope_cwd", os.getcwd())
        write_text(state_dir / "include_all", "1" if include_all else "0")

        selected = picker.run_fzf(state_dir, include_all)
        if not selected:
            return 0

        if read_state_mode(state_dir) == "dialogues":
            session_id = read_text(state_dir / "session_id")
            session_cwd = read_text(state_dir / "cwd")
        else:
            fields = selected.split("\t")
            session_id = fields[0] if fields else ""
            if session_id == "__DIVIDER__" or not session_id:
                return 0
            session_cwd = fields[3] if len(fields) > 3 else os.getcwd()

        if not session_id or not session_cwd:
            return 0
        if not config.resume_bin:
            print(
                f"{config.resume_command} was not found in PATH. Install it or set {config.resume_env}.",
                file=sys.stderr,
            )
            return 1

        print(f"{config.resume_message} {session_cwd}")
        os.chdir(session_cwd)
        os.execvp(config.resume_bin, [config.resume_bin, *config.resume_args, session_id])
    return 1
