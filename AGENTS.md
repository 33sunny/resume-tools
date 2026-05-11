# Agent Notes

Read `README.md` first, then this file.

This repo intentionally keeps provider logic separate from the terminal UI:

- `resume_picker/ui.py`: fzf layout, key bindings, preview rendering, session rows, dialogue drill-down.
- `resume_picker/text.py`: visual width, date grouping, dividers, markdown/highlight helpers.
- `resume_picker/providers/claude.py`: Claude Code JSONL parsing and resume command config.
- `resume_picker/providers/codex.py`: Codex JSONL parsing, `session_index.jsonl` compatibility, and Codex/proxy command config.

When changing UI behavior, prefer changing shared code in `resume_picker/ui.py` or `resume_picker/text.py` so all three commands stay aligned.

Local comparison commands should exist in `/Users/shan/bin`:

- `claude-resume-old`
- `codex-resume-old`
- `codex-proxy-resume-old`

Do not remove those while UI parity is still being checked.
