# Unified Resume Tools Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build one shared local session picker that powers `claude-resume`, `codex-resume`, and `codex-proxy-resume`.

**Architecture:** Keep provider-specific session parsing in small adapters, and move fzf UI, row rendering, preview rendering, search, and resume flow into `resume_picker`. Keep the existing command names for daily use, and expose `*-old` commands for comparing the previous implementations.

**Tech Stack:** Python 3 standard library, `fzf`, local Claude/Codex JSONL session files, shell symlinks in `/Users/shan/bin`.

---

### Task 1: Create Shared Project Skeleton

**Files:**
- Create: `resume_picker/models.py`
- Create: `resume_picker/text.py`
- Create: `resume_picker/ui.py`
- Create: `resume_picker/providers/claude.py`
- Create: `resume_picker/providers/codex.py`
- Create: `resume_picker/cli.py`
- Create: `bin/claude-resume`
- Create: `bin/codex-resume`
- Create: `bin/codex-proxy-resume`

**Steps:**
1. Define shared `Session` and `Dialogue` models.
2. Move visual width, date grouping, markdown rendering, and highlighting helpers into shared modules.
3. Implement provider adapters for Claude and Codex.
4. Implement the fzf UI and helper action state machine once in `resume_picker/ui.py`.
5. Add wrapper commands that dispatch by command name.

### Task 2: Preserve Old Commands for Comparison

**Files:**
- Modify symlinks in `/Users/shan/bin`

**Steps:**
1. Create `claude-resume-old`, `codex-resume-old`, and `codex-proxy-resume-old` symlinks to the existing projects.
2. Point `claude-resume`, `codex-resume`, and `codex-proxy-resume` to the new project.
3. Verify each command resolves to the intended target.

### Task 3: Verify Behavior

**Commands:**
- `python3 -m py_compile ...`
- `bin/codex-proxy-resume -a --list`
- `bin/codex-resume -a --list`
- `bin/claude-resume -a --list`

**Expected:**
- All Python files compile.
- All three commands show the same UI grouping style.
- The `*-old` commands remain callable for comparison.
