# TODO

## 后续 UI 优化

- 继续优化 Codex 工具调用摘要，让它更接近实时 Codex CLI UI。session 日志里保存的是 `exec_command` 这类底层调用，而实时 UI 会二次归类成 `Explored`、`Search`、`Read`、`List` 等展示。

- 如果未来 fzf 支持运行时修改颜色，可以继续优化右侧 preview 的焦点提示。目前 fzf 支持动态切换 preview 边框样式，但不支持动态切换 `preview-border` 颜色。

- 继续优化 round preview 里的按 message 边界翻页。当前 `Shift+↑` / `Shift+↓` 使用已缓存的预览文本和 message anchors，未来可以继续微调 anchor 规则，减少翻页后的上下文丢失。

- 为复杂 round preview 增加基于 fixture 的展示快照测试，重点覆盖 interrupted turn、`Updated Plan` 和较长工具调用摘要组。
