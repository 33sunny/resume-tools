import unittest
import re

from resume_picker.models import Dialogue, DialogueActivity, PlanStep, PlanUpdate
from resume_picker.ui import (
    dialogue_activity_lines,
    dialogue_blocks,
    dialogue_role_groups,
    message_divider,
    plan_update_lines,
    preview_page_offset,
    tool_summary_lines,
)


ANSI_RE = re.compile(r"\033\[[0-9;]*m")


class DialogueBlockTests(unittest.TestCase):
    def test_groups_user_with_following_assistant_messages(self):
        dialogues = [
            Dialogue("user", 1, "first question"),
            Dialogue("assistant", 2, "first answer part 1"),
            Dialogue("assistant", 3, "first answer part 2"),
            Dialogue("user", 4, "second question"),
            Dialogue("assistant", 5, "second answer"),
        ]

        blocks = dialogue_blocks(dialogues)

        self.assertEqual(
            [(block.num, block.start_num, block.end_num) for block in blocks],
            [
                (1, 1, 3),
                (2, 4, 5),
            ],
        )
        self.assertEqual(
            [[dialogue.num for dialogue in block.dialogues] for block in blocks],
            [
                [1, 2, 3],
                [4, 5],
            ],
        )

    def test_preserves_leading_assistant_messages(self):
        dialogues = [
            Dialogue("assistant", 1, "leading answer"),
            Dialogue("user", 2, "question"),
            Dialogue("assistant", 3, "answer"),
        ]

        blocks = dialogue_blocks(dialogues)

        self.assertEqual(
            [(block.num, block.start_num, block.end_num) for block in blocks],
            [
                (1, 1, 1),
                (2, 2, 3),
            ],
        )

    def test_merges_consecutive_user_messages_before_assistant_response(self):
        dialogues = [
            Dialogue("user", 1, "first image caption"),
            Dialogue("user", 2, "follow-up question"),
            Dialogue("assistant", 3, "answer"),
            Dialogue("user", 4, "new image caption"),
            Dialogue("user", 5, "replacement question"),
        ]

        blocks = dialogue_blocks(dialogues)

        self.assertEqual(
            [(block.num, block.start_num, block.end_num) for block in blocks],
            [
                (1, 1, 3),
                (2, 4, 5),
            ],
        )
        self.assertEqual(
            [[dialogue.num for dialogue in block.dialogues] for block in blocks],
            [
                [1, 2, 3],
                [4, 5],
            ],
        )

    def test_interrupted_user_message_continues_previous_block(self):
        dialogues = [
            Dialogue("user", 1, "original request"),
            Dialogue("assistant", 2, "partial answer"),
            Dialogue("user", 3, "correction after interrupt", continues_previous=True),
            Dialogue("assistant", 4, "revised answer"),
            Dialogue("user", 5, "next request"),
        ]

        blocks = dialogue_blocks(dialogues)

        self.assertEqual(
            [[dialogue.num for dialogue in block.dialogues] for block in blocks],
            [
                [1, 2, 3, 4],
                [5],
            ],
        )

    def test_dialogue_role_groups_keep_message_boundaries_inside_role_runs(self):
        dialogues = [
            Dialogue("user", 65, "first user message"),
            Dialogue("user", 66, "corrected user message"),
            Dialogue("assistant", 67, "first answer"),
            Dialogue("assistant", 68, "second answer"),
            Dialogue("user", 69, "next question"),
        ]

        groups = dialogue_role_groups(dialogues)

        self.assertEqual([[dialogue.num for dialogue in group] for group in groups], [[65, 66], [67, 68], [69]])

    def test_message_divider_starts_at_left_edge(self):
        plain = ANSI_RE.sub("", message_divider(82, 100))

        self.assertTrue(plain.startswith("┄┄┄┄┄ message 82 "))

    def test_tool_summary_lines_are_dim_one_line_summaries(self):
        dialogue = Dialogue("assistant", 82, "answer", tool_summaries=("Bash ghostty +show-config | grep copy-on-select",))

        lines = tool_summary_lines(dialogue, 48)
        plain = [ANSI_RE.sub("", line) for line in lines]

        self.assertEqual(len(lines), 1)
        self.assertEqual(plain[0], "↳ tool: Bash ghostty +show-config | grep copy…")

    def test_tool_summary_lines_collapse_after_two_tools(self):
        dialogue = Dialogue(
            "assistant",
            82,
            "answer",
            tool_summaries=("Read a", "Read b", "Read c", "Read d", "Read e"),
        )

        lines = tool_summary_lines(dialogue, 100)
        plain = [ANSI_RE.sub("", line) for line in lines]

        self.assertEqual(plain, ["↳ tool: Read a", "↳ tool: Read b", "↳ … +3 more tools"])

    def test_plan_update_lines_show_progress_steps(self):
        dialogue = Dialogue(
            "assistant",
            12,
            "working",
            plan_updates=(
                PlanUpdate(
                    steps=(
                        PlanStep("删除 V3 旧 archive 空框架", "completed"),
                        PlanStep("实现 04 initial entity plan runner", "in_progress"),
                        PlanStep("更新文档和做基础校验", "pending"),
                    ),
                    explanation="先跑第一段。",
                ),
            ),
        )

        lines = plan_update_lines(dialogue, 80)
        plain = [ANSI_RE.sub("", line) for line in lines]

        self.assertEqual(
            plain,
            [
                "• Updated Plan",
                "↳ ✓ 删除 V3 旧 archive 空框架",
                "  □ 实现 04 initial entity plan runner",
                "  □ 更新文档和做基础校验",
            ],
        )

    def test_dialogue_activity_lines_preserve_plan_tool_order(self):
        first_plan = PlanUpdate(
            steps=(
                PlanStep("移走 V3 旧空框架", "in_progress"),
                PlanStep("创建按 location 聚合的新目录", "pending"),
            )
        )
        second_plan = PlanUpdate(
            steps=(
                PlanStep("移走 V3 旧空框架", "completed"),
                PlanStep("创建按 location 聚合的新目录", "in_progress"),
            )
        )
        dialogue = Dialogue(
            "assistant",
            12,
            "working",
            activities=(
                DialogueActivity(kind="plan", plan_update=first_plan),
                DialogueActivity(kind="tool", text="exec_command find cases"),
                DialogueActivity(kind="tool", text="exec_command mkdir a"),
                DialogueActivity(kind="tool", text="exec_command mkdir b"),
                DialogueActivity(kind="tool", text="exec_command mkdir c"),
                DialogueActivity(kind="plan", plan_update=second_plan),
            ),
        )

        lines = dialogue_activity_lines(dialogue, 100)
        plain = [ANSI_RE.sub("", line) for line in lines]

        self.assertEqual(
            plain,
            [
                "• Updated Plan",
                "↳ □ 移走 V3 旧空框架",
                "  □ 创建按 location 聚合的新目录",
                "",
                "↳ tool: exec_command find cases",
                "↳ tool: exec_command mkdir a",
                "↳ … +2 more tools",
                "",
                "• Updated Plan",
                "↳ ✓ 移走 V3 旧空框架",
                "  □ 创建按 location 聚合的新目录",
            ],
        )

    def test_page_down_uses_previous_message_when_next_message_has_no_content_visible(self):
        lines = [
            "header",
            "┄┄┄┄┄ message 1 ┄┄",
            "content 1",
            "┄┄┄┄┄ message 2 ┄┄",
            "content 2",
            "┄┄┄┄┄ message 3 ┄┄",
            "content 3",
            "┄┄┄┄┄ message 4 ┄┄",
            "content 4",
            "┄┄┄┄┄ message 5 ┄┄",
            "content 5",
            "┄┄┄┄┄ message 6 ┄┄",
            "content 6",
            "┄┄┄┄┄ message 7 ┄┄",
            "content 7",
        ]

        self.assertEqual(preview_page_offset(lines, 0, 14, 100, 1), 11)

    def test_page_down_uses_next_message_when_its_content_is_visible(self):
        lines = [
            "header",
            "┄┄┄┄┄ message 1 ┄┄",
            "content 1",
            "┄┄┄┄┄ message 2 ┄┄",
            "content 2",
            "┄┄┄┄┄ message 3 ┄┄",
            "content 3",
            "┄┄┄┄┄ message 4 ┄┄",
            "content 4",
            "┄┄┄┄┄ message 5 ┄┄",
            "content 5",
            "┄┄┄┄┄ message 6 ┄┄",
            "content 6",
            "┄┄┄┄┄ message 7 ┄┄",
            "content 7",
        ]

        self.assertEqual(preview_page_offset(lines, 0, 15, 100, 1), 13)


if __name__ == "__main__":
    unittest.main()
