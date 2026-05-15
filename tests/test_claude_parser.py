import json
import tempfile
import unittest
from pathlib import Path

from resume_picker.models import Session
from resume_picker.providers.claude import ClaudeProvider
from resume_picker.ui import dialogue_blocks


def jsonl_entry(entry: dict) -> str:
    return json.dumps(entry, ensure_ascii=False)


def user_entry(text: str) -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def assistant_entry(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


class ClaudeParserTests(unittest.TestCase):
    def test_interrupt_marker_and_followup_continue_previous_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            path.write_text(
                "\n".join(
                    jsonl_entry(entry)
                    for entry in [
                        user_entry("original request"),
                        assistant_entry("partial answer"),
                        user_entry("[Request interrupted by user]"),
                        user_entry("correction after interrupt"),
                        assistant_entry("revised answer"),
                    ]
                ),
                encoding="utf-8",
            )
            session = Session(
                id="session",
                title="title",
                cwd="/tmp",
                provider="claude",
                created_at="2026-05-15T00:00:00+00:00",
                updated_at="2026-05-15T00:00:00+00:00",
                path=path,
            )

            dialogues = ClaudeProvider().parse_dialogues(session)
            blocks = dialogue_blocks(dialogues)

        self.assertEqual(
            [(dialogue.role, dialogue.text, dialogue.continues_previous) for dialogue in dialogues],
            [
                ("user", "original request", False),
                ("assistant", "partial answer", False),
                ("user", "[Request interrupted by user]", True),
                ("user", "correction after interrupt", True),
                ("assistant", "revised answer", False),
            ],
        )
        self.assertEqual([[dialogue.num for dialogue in block.dialogues] for block in blocks], [[1, 2, 3, 4, 5]])


if __name__ == "__main__":
    unittest.main()
