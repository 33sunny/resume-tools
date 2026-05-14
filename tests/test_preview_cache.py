import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from resume_picker.models import Dialogue, ProviderConfig, Session
from resume_picker.ui import Picker, read_preview_cache, write_preview_cache, write_text


class FakeProvider:
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
        self.parse_count = 0
        self.session = Session(
            id="session",
            title="title",
            cwd="/tmp",
            provider="fake",
            created_at="2026-05-13T00:00:00+00:00",
            updated_at="2026-05-13T00:00:00+00:00",
            path=Path("/tmp/session.jsonl"),
        )

    def load_sessions(self) -> list[Session]:
        return [self.session]

    def parse_dialogues(self, session: Session) -> list[Dialogue]:
        self.parse_count += 1
        return [Dialogue("user", 1, "hello")]


class PreviewCacheTests(unittest.TestCase):
    def test_preview_cache_round_trips_rendered_lines_and_anchors(self):
        lines = [
            "header",
            "┄┄┄┄┄ message 1 ┄┄",
            "content 1",
            "┄┄┄┄┄ message 2 ┄┄",
            "content 2",
        ]

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_preview_cache(state_dir, "session\tblocks\t1\t", lines, 100)
            cache = read_preview_cache(state_dir, "session\tblocks\t1\t", 100)

        self.assertIsNotNone(cache)
        cached_lines, starts, anchors = cache
        self.assertEqual(cached_lines, lines)
        self.assertEqual(starts, [0, 1, 2, 3, 4])
        self.assertEqual(anchors, [(1, 1, 2), (3, 3, 4)])

    def test_preview_cache_rejects_different_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_preview_cache(state_dir, "key", ["hello"], 100)

            self.assertIsNone(read_preview_cache(state_dir, "key", 80))

    def test_preview_cache_preserves_trailing_blank_lines(self):
        lines = ["before", "", "after", ""]

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_preview_cache(state_dir, "key", lines, 100)
            cache = read_preview_cache(state_dir, "key", 100)

        self.assertIsNotNone(cache)
        cached_lines, _starts, _anchors = cache
        self.assertEqual(cached_lines, lines)

    def test_preview_helper_reuses_cache_on_refresh(self):
        provider = FakeProvider()
        picker = Picker(provider, Path("fake"), "fake")

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_text(state_dir / "mode", "dialogues")
            write_text(state_dir / "focus", "preview")
            write_text(state_dir / "session_id", "session")
            write_text(state_dir / "dialogue_view", "messages")
            write_text(state_dir / "keyword", "")

            with contextlib.redirect_stdout(io.StringIO()):
                picker.helper_main(state_dir, "preview", ["1", ""])
            with contextlib.redirect_stdout(io.StringIO()):
                picker.helper_main(state_dir, "preview", ["1", ""])

        self.assertEqual(provider.parse_count, 1)

    def test_preview_page_transform_resets_fzf_internal_scroll(self):
        provider = FakeProvider()
        picker = Picker(provider, Path("fake"), "fake")

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_text(state_dir / "mode", "dialogues")
            write_text(state_dir / "focus", "preview")
            write_text(state_dir / "session_id", "session")
            write_text(state_dir / "dialogue_view", "messages")
            write_text(state_dir / "keyword", "")

            with contextlib.redirect_stdout(io.StringIO()):
                picker.helper_main(state_dir, "preview", ["1", ""])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                picker.helper_main(state_dir, "page-down-transform", ["1", ""])

        self.assertEqual(output.getvalue().strip(), "refresh-preview+preview-top")

    def test_preview_page_transform_works_from_dialogue_list_focus(self):
        provider = FakeProvider()
        picker = Picker(provider, Path("fake"), "fake")

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_text(state_dir / "mode", "dialogues")
            write_text(state_dir / "focus", "list")
            write_text(state_dir / "session_id", "session")
            write_text(state_dir / "dialogue_view", "messages")
            write_text(state_dir / "keyword", "")

            with contextlib.redirect_stdout(io.StringIO()):
                picker.helper_main(state_dir, "preview", ["1", ""])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                picker.helper_main(state_dir, "page-down-transform", ["1", ""])

        self.assertEqual(output.getvalue().strip(), "refresh-preview+preview-top")


if __name__ == "__main__":
    unittest.main()
