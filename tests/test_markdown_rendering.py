import re
import unittest

from resume_picker.text import render_markdown_lines


ANSI_RE = re.compile(r"\033\[[0-9;:]*m")


class MarkdownRenderingTests(unittest.TestCase):
    def test_fenced_code_block_uses_padded_background_without_fences(self):
        lines = render_markdown_lines("before\n```bash\npython3 -m unittest discover\n```\nafter", 48)
        plain = [ANSI_RE.sub("", line) for line in lines]

        self.assertEqual(plain[0], "before")
        self.assertEqual(plain[1], "")
        self.assertEqual(plain[2], "  " + (" " * 42))
        self.assertTrue(plain[3].startswith("    python3 -m unittest discover"))
        self.assertEqual(len(plain[3]), 44)
        self.assertEqual(plain[4], "  " + (" " * 42))
        self.assertEqual(plain[5], "")
        self.assertEqual(plain[6], "after")
        self.assertFalse(any("```" in line for line in plain))

    def test_fenced_code_block_wraps_long_lines_inside_block_width(self):
        lines = render_markdown_lines("```bash\nabcdef ghijkl mnopqr stuvwx yz\n```", 24)
        plain = [ANSI_RE.sub("", line) for line in lines]

        code_lines = plain[2:-2]
        self.assertGreater(len(code_lines), 1)
        self.assertTrue(all(len(line) == 26 for line in code_lines))
        self.assertTrue(all(line.startswith("    ") for line in code_lines))

    def test_inline_code_does_not_parse_partial_fence_marker(self):
        lines = render_markdown_lines("只把 ```bash / ```text 这种 fenced block 渲染成灰底。", 80)
        plain = [ANSI_RE.sub("", line) for line in lines]

        self.assertEqual(plain, ["只把 ```bash / ```text 这种 fenced block 渲染成灰底。"])

    def test_indented_fenced_code_block_is_rendered_as_code_block(self):
        lines = render_markdown_lines("  ``` text\n    GET https://restapi.amap.com/v5/place/text\n  ```", 56)
        plain = [ANSI_RE.sub("", line) for line in lines]

        self.assertFalse(any("```" in line for line in plain))
        self.assertTrue(any("GET https://restapi.amap.com/v5/place/text" in line for line in plain))
        self.assertTrue(all(line.startswith("  ") for line in plain[1:-1]))

    def test_local_markdown_file_link_renders_path_on_its_own_line(self):
        lines = render_markdown_lines(
            "- [evidence_reasoning.py](/Users/shan/project/pipeline/v1/common/evidence_reasoning.py): 生成 textContext",
            100,
        )
        plain = [ANSI_RE.sub("", line) for line in lines]

        self.assertEqual(
            plain,
            [
                "- evidence_reasoning.py: 生成 textContext",
                "  /Users/shan/project/pipeline/v1/common/evidence_reasoning.py",
            ],
        )

    def test_quote_block_uses_colored_bar_and_preserves_markdown(self):
        lines = render_markdown_lines(
            "> 更细一点的话，可以做成两层：\n"
            ">\n"
            "> - 连续 `>` 行合并为一个 quote block。\n"
            "> - [README.md](/Users/shan/project/README.md): 保留链接渲染。\n"
            "---\n"
            "可以，就这样吧。",
            100,
        )
        plain = [ANSI_RE.sub("", line) for line in lines]

        self.assertEqual(
            plain,
            [
                "▌ 更细一点的话，可以做成两层：",
                "▌",
                "▌ - 连续 > 行合并为一个 quote block。",
                "▌ - README.md: 保留链接渲染。",
                "▌   /Users/shan/project/README.md",
                "---",
                "可以，就这样吧。",
            ],
        )
        self.assertTrue(lines[0].startswith("\033[38;2;137;180;250m▌\033[0m "))

    def test_long_quote_lines_wrap_with_quote_bar_on_each_line(self):
        lines = render_markdown_lines(
            "> 上海是顺序探店，大量真实店名不在口播里，所以后续必须支持视觉找店名再搜 POI。",
            36,
        )
        plain = [ANSI_RE.sub("", line) for line in lines]

        self.assertGreater(len(plain), 1)
        self.assertTrue(all(line.startswith("▌ ") for line in plain))
        self.assertNotIn("▌ -", plain)

    def test_long_quote_list_item_does_not_wrap_after_marker_only(self):
        lines = render_markdown_lines(
            "> - 上海是顺序探店，大量真实店名不在口播里，所以后续必须支持视觉找店名再搜 POI。",
            36,
        )
        plain = [ANSI_RE.sub("", line) for line in lines]

        self.assertGreater(len(plain), 1)
        self.assertTrue(all(line.startswith("▌ ") for line in plain))
        self.assertNotIn("▌ -", plain)


if __name__ == "__main__":
    unittest.main()
