# resume-tools

本地 AI 编程会话的终端恢复工具。它用一套统一的 `fzf` 交互界面，搜索、预览并恢复 Claude Code、Codex CLI 和 codex-proxy CLI 的本机会话。

这个项目主要解决两个问题：

- 原生命令的 resume 列表信息不够好找，尤其是需要跨目录、跨配置查历史会话时。
- Claude Code、Codex CLI、codex-proxy CLI 的会话来源不同，但日常使用时需要一套一致的列表、预览、搜索和恢复体验。

## 命令

- `claude-resume`：读取 `~/.claude/projects/**/*.jsonl`，并用 `claude --resume <session-id>` 恢复会话。
- `codex-resume`：读取原生 Codex CLI 会话，并用 `codex resume <session-id>` 恢复会话。
- `codex-proxy-resume`：读取 codex-proxy CLI 会话，并用 `codex-proxy resume <session-id>` 恢复会话。

## 功能

- 按当前目录筛选会话，也可以用 `-a` 查看全部本机会话。
- 用 `fzf` 搜索会话标题、目录和对话内容。
- 右侧预览完整对话内容，支持普通 message 视图和 round 视图。
- `Shift+Tab` 在 message 视图和 round 视图之间切换。
- 右侧 preview 聚焦后，`↑/↓` 逐行滚动，`Shift+↑/Shift+↓` 按页滚动。
- `F5` 刷新会话列表或当前对话详情。
- Codex 的 `Updated Plan` 会按原始顺序展示在对应回复里，并保留工具调用摘要。
- 本地文件链接会拆成文件名和路径两行，方便复制路径或定位文件。

## 依赖

- macOS 或常见 Unix shell 环境。
- Python 3，只使用标准库。
- `fzf`。
- 已安装并登录对应的 `claude`、`codex`、`codex-proxy` 命令。

## 安装

在项目目录下执行：

```bash
./install.sh
```

安装脚本会把下面三个命令链接到 `~/bin`：

```text
claude-resume
codex-resume
codex-proxy-resume
```

如果你的 shell 没有把 `~/bin` 放进 `PATH`，需要先把它加入 shell 配置。

## 使用

查看当前目录下的会话：

```bash
codex-resume
codex-proxy-resume
claude-resume
```

查看所有目录下的会话：

```bash
codex-resume -a
codex-proxy-resume -a
claude-resume -a
```

只输出列表，不进入交互界面：

```bash
codex-resume -a --list
codex-proxy-resume -a --list
claude-resume -a --list
```

## 项目结构

```text
bin/                         命令入口
resume_picker/ui.py          fzf UI、快捷键、预览渲染
resume_picker/text.py        终端宽度、日期分组、Markdown 渲染
resume_picker/providers/     Claude / Codex 会话解析
tests/                       单元测试
```

## 开发检查

修改代码后建议跑：

```bash
python3 -m unittest discover
python3 -m py_compile resume_picker/*.py resume_picker/providers/*.py tests/*.py bin/claude-resume bin/codex-resume bin/codex-proxy-resume
git diff --check
```

## 许可证

MIT
