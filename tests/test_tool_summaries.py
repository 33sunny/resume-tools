import unittest

from resume_picker.providers.claude import extract_claude_tool_summaries
from resume_picker.providers.codex import summarize_codex_tool_call


class ToolSummaryTests(unittest.TestCase):
    def test_claude_tool_summary_uses_command_or_file_path_without_payload(self):
        message = {
            "content": [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {
                        "command": "ghostty +show-config | grep '^copy-on-select'",
                        "description": "Check Ghostty config",
                    },
                },
                {
                    "type": "tool_use",
                    "name": "Write",
                    "input": {
                        "file_path": "/Users/shan/bin/claude-resume-preview.py",
                        "content": "very long file content should not appear",
                    },
                },
            ]
        }

        self.assertEqual(
            extract_claude_tool_summaries(message),
            (
                "Bash ghostty +show-config | grep '^copy-on-select'",
                "Write /Users/shan/bin/claude-resume-preview.py",
            ),
        )

    def test_codex_tool_summary_uses_command_or_target_path_without_payload(self):
        self.assertEqual(
            summarize_codex_tool_call(
                {
                    "name": "exec_command",
                    "arguments": '{"cmd":"python3 -m unittest discover","workdir":"/Users/shan/projects/productivity/resume-tools"}',
                }
            ),
            "exec_command python3 -m unittest discover",
        )
        self.assertEqual(
            summarize_codex_tool_call(
                {
                    "name": "apply_patch",
                    "arguments": "*** Begin Patch\n*** Update File: resume_picker/ui.py\n@@\n",
                }
            ),
            "apply_patch resume_picker/ui.py",
        )


if __name__ == "__main__":
    unittest.main()
