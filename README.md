# resume-tools

Shared interactive `fzf` pickers for resuming local Claude Code and Codex CLI sessions.

共享的本地会话恢复工具，用同一套终端 UI 恢复 Claude Code、Codex CLI、codex-proxy CLI 会话。

## Commands

- `claude-resume`: reads `~/.claude/projects/**/*.jsonl` and resumes with `claude --resume <session-id>`
- `codex-resume`: reads native Codex CLI sessions and resumes with `codex resume <session-id>`
- `codex-proxy-resume`: reads proxy Codex CLI sessions and resumes with `codex-proxy resume <session-id>`

## Local Comparison Commands

During the migration, `/Users/shan/bin` keeps old implementations available:

- `claude-resume-old`
- `codex-resume-old`
- `codex-proxy-resume-old`

Use the normal command names for the shared UI, and use `*-old` when you want to compare behavior against the previous standalone projects.

## Install

For this machine:

```bash
./install.sh
```

The install script points the three normal command names in `~/bin` at this project. It does not manage the local `*-old` comparison wrappers.

## Development

The shared picker UI lives in `resume_picker/ui.py`. Provider-specific session parsing lives under `resume_picker/providers/`.

Use these non-interactive checks while iterating:

```bash
python3 -m py_compile resume_picker/*.py resume_picker/providers/*.py bin/claude-resume bin/codex-resume bin/codex-proxy-resume
bin/claude-resume -a --list
bin/codex-resume -a --list
bin/codex-proxy-resume -a --list
```
