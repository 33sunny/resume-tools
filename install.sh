#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${HOME}/bin"

mkdir -p "$BIN_DIR"

ln -sfn "$ROOT/bin/claude-resume" "$BIN_DIR/claude-resume"
ln -sfn "$ROOT/bin/codex-resume" "$BIN_DIR/codex-resume"
ln -sfn "$ROOT/bin/codex-proxy-resume" "$BIN_DIR/codex-proxy-resume"

echo "Installed resume-tools commands into $BIN_DIR"
