import json
import tempfile
import unittest
from pathlib import Path

from resume_picker.providers.codex import CodexProvider


class CodexParserTests(unittest.TestCase):
    def test_attaches_update_plan_to_assistant_dialogue(self):
        entries = [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "starting work"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "update_plan",
                    "arguments": json.dumps(
                        {
                            "explanation": "先跑第一段。",
                            "plan": [
                                {"step": "删除 V3 旧 archive 空框架", "status": "completed"},
                                {"step": "实现 04 initial entity plan runner", "status": "in_progress"},
                                {"step": "更新文档和做基础校验", "status": "pending"},
                            ],
                        }
                    ),
                },
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")

            dialogues = CodexProvider("codex").parse_dialogues_path(path)

        self.assertEqual(len(dialogues), 1)
        self.assertEqual(dialogues[0].text, "starting work")
        self.assertEqual(dialogues[0].tool_summaries, ())
        self.assertEqual(len(dialogues[0].plan_updates), 1)
        self.assertEqual([activity.kind for activity in dialogues[0].activities], ["plan"])
        plan = dialogues[0].plan_updates[0]
        self.assertEqual(plan.explanation, "先跑第一段。")
        self.assertEqual(
            [(step.step, step.status) for step in plan.steps],
            [
                ("删除 V3 旧 archive 空框架", "completed"),
                ("实现 04 initial entity plan runner", "in_progress"),
                ("更新文档和做基础校验", "pending"),
            ],
        )

    def test_preserves_plan_and_tool_activity_order(self):
        first_plan = {
            "plan": [
                {"step": "第一步", "status": "in_progress"},
                {"step": "第二步", "status": "pending"},
            ]
        }
        second_plan = {
            "plan": [
                {"step": "第一步", "status": "completed"},
                {"step": "第二步", "status": "in_progress"},
            ]
        }
        entries = [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "starting work"}],
                },
            },
            {
                "type": "response_item",
                "payload": {"type": "function_call", "name": "update_plan", "arguments": json.dumps(first_plan)},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": "find pipeline/v3/cases -maxdepth 2 -type d | sort"}),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": "mkdir -p pipeline/v3/cases/demo"}),
                },
            },
            {
                "type": "response_item",
                "payload": {"type": "function_call", "name": "update_plan", "arguments": json.dumps(second_plan)},
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")

            dialogues = CodexProvider("codex").parse_dialogues_path(path)

        self.assertEqual([activity.kind for activity in dialogues[0].activities], ["plan", "tool", "tool", "plan"])
        self.assertEqual(
            [activity.text for activity in dialogues[0].activities if activity.kind == "tool"],
            [
                "exec_command find pipeline/v3/cases -maxdepth 2 -type d | sort",
                "exec_command mkdir -p pipeline/v3/cases/demo",
            ],
        )

    def test_marks_next_user_message_after_turn_aborted_as_continuation(self):
        entries = [
            {
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "original request"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "partial answer"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<turn_aborted>\nThe user interrupted the previous turn on purpose.\n</turn_aborted>",
                        }
                    ],
                },
            },
            {"type": "event_msg", "payload": {"type": "turn_aborted", "reason": "interrupted"}},
            {
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "correction after interrupt"},
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")

            dialogues = CodexProvider("codex").parse_dialogues_path(path)

        self.assertEqual([(dialogue.role, dialogue.text) for dialogue in dialogues], [
            ("user", "original request"),
            ("assistant", "partial answer"),
            ("user", "correction after interrupt"),
        ])
        self.assertFalse(dialogues[0].continues_previous)
        self.assertFalse(dialogues[1].continues_previous)
        self.assertTrue(dialogues[2].continues_previous)


if __name__ == "__main__":
    unittest.main()
