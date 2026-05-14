import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from resume_picker.models import Dialogue, ProviderConfig, Session
from resume_picker.ui import Picker, first_selectable_row_position, read_text, write_preview_cache, write_text


class RefreshProvider:
    def __init__(self) -> None:
        self.config = ProviderConfig(
            mode="fake",
            session_label="Fake",
            resume_command="fake",
            resume_env="FAKE",
            resume_bin=None,
            temp_prefix="fake-",
            resume_args=(),
            resume_message="resume",
        )
        self.sessions = [
            Session(
                id="old-session",
                title="old title",
                cwd="/tmp/project",
                provider="fake",
                created_at="2026-05-13T00:00:00+00:00",
                updated_at="2026-05-13T00:00:00+00:00",
                path=Path("/tmp/old.jsonl"),
            )
        ]
        self.dialogues = [Dialogue("user", 1, "old question")]

    def load_sessions(self) -> list[Session]:
        return self.sessions

    def parse_dialogues(self, session: Session) -> list[Dialogue]:
        return self.dialogues


class RefreshTests(unittest.TestCase):
    def test_refresh_sessions_reloads_rows_from_provider(self):
        provider = RefreshProvider()
        picker = Picker(provider, Path("fake"), "fake")

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_text(state_dir / "mode", "sessions")
            write_text(state_dir / "sessions.txt", picker.session_rows(provider.sessions))
            write_text(state_dir / "keyword", "")
            write_text(state_dir / "scope_cwd", "/tmp/project")
            write_text(state_dir / "include_all", "0")
            provider.sessions = [
                Session(
                    id="new-session",
                    title="new title",
                    cwd="/tmp/project",
                    provider="fake",
                    created_at="2026-05-14T00:00:00+00:00",
                    updated_at="2026-05-14T00:00:00+00:00",
                    path=Path("/tmp/new.jsonl"),
                )
            ]

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                picker.helper_main(state_dir, "refresh-transform", ["old-session", "0", ""])

            refreshed_rows = read_text(state_dir / "sessions.txt")

        self.assertIn("new-session", refreshed_rows)
        self.assertIn("reload-sync(", output.getvalue())
        self.assertIn(f"+pos({first_selectable_row_position(refreshed_rows)})+refresh-preview", output.getvalue())

    def test_refresh_dialogues_resets_preview_cache_and_keeps_current_row(self):
        provider = RefreshProvider()
        picker = Picker(provider, Path("fake"), "fake")

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_text(state_dir / "mode", "dialogues")
            write_text(state_dir / "focus", "list")
            write_text(state_dir / "session_id", "old-session")
            write_text(state_dir / "dialogue_view", "messages")
            write_text(state_dir / "keyword", "")
            write_preview_cache(state_dir, "stale", ["cached"], 100)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                picker.helper_main(state_dir, "refresh-transform", ["1", "0", ""])

            cache_key = read_text(state_dir / "preview_cache_key")

        self.assertEqual(cache_key, "")
        self.assertIn("reload-sync(", output.getvalue())
        self.assertIn("+pos(1)+refresh-preview", output.getvalue())


if __name__ == "__main__":
    unittest.main()
