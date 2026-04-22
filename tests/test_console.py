"""Tests for the console Rich helpers."""
import io

from rich.console import Console

from tracksplit.console import make_console, status_text, summary_panel


class TestMakeConsole:
    def test_returns_console(self):
        con = make_console()
        assert isinstance(con, Console)

    def test_highlight_disabled(self):
        con = make_console()
        assert con._highlight is False

    def test_custom_file(self):
        buf = io.StringIO()
        con = make_console(file=buf)
        con.print("hello")
        assert "hello" in buf.getvalue()


class TestStatusText:
    def test_done(self):
        t = status_text("done", "video.mkv")
        plain = t.plain
        assert "video.mkv" in plain

    def test_skipped_with_detail(self):
        t = status_text("skipped", "video.mkv", detail="unchanged")
        plain = t.plain
        assert "unchanged" in plain

    def test_error_with_detail(self):
        t = status_text("error", "video.mkv", detail="ffprobe failed")
        plain = t.plain
        assert "ffprobe failed" in plain

    def test_brackets_in_name_not_escaped(self):
        name = "2025 - Afrojack [kineticFIELD].mkv"
        for status in ("done", "skipped", "error", "cancelled"):
            t = status_text(status, name)
            assert name in t.plain
            assert "\\[" not in t.plain
            assert "\\]" not in t.plain

    def test_brackets_in_detail_not_escaped(self):
        detail = "missing [audio] stream"
        for status in ("skipped", "error", "cancelled"):
            t = status_text(status, "video.mkv", detail=detail)
            assert detail in t.plain
            assert "\\[" not in t.plain
            assert "\\]" not in t.plain


class TestSummaryPanel:
    def test_all_success(self):
        panel = summary_panel(processed=3, skipped=0, failed=0)
        assert panel is not None

    def test_with_failures(self):
        panel = summary_panel(processed=2, skipped=1, failed=1)
        assert panel is not None
