"""Tests for gray_matter.webgui — CLI argv building, icon resolution, _say safety."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# _cli_argv
# ---------------------------------------------------------------------------

class TestCliArgv:
    def test_known_tool(self):
        from gray_matter.webgui import _cli_argv
        argv = _cli_argv("neuron", "status")
        assert "status" in argv
        assert "-m" in argv
        assert len(argv) >= 3

    def test_unknown_tool_raises(self):
        from gray_matter.webgui import _cli_argv
        with pytest.raises(ValueError, match="sconosciuto"):
            _cli_argv("nonexistent-tool", "cmd")


# ---------------------------------------------------------------------------
# _argv_for
# ---------------------------------------------------------------------------

class TestArgvFor:
    def test_positional_and_flags(self):
        from gray_matter.webgui import _argv_for
        args = {
            "_order": ["name", "verbose"],
            "_spec": {
                "name": {},
                "verbose": {"is_flag": True, "flag": "--verbose"},
            },
            "name": "myproject",
            "verbose": True,
        }
        argv = _argv_for("neurag", "add", args)
        assert "add" in argv
        assert "myproject" in argv
        assert "--verbose" in argv

    def test_empty_value_skipped(self):
        from gray_matter.webgui import _argv_for
        args = {
            "_order": ["name"],
            "_spec": {"name": {"flag": "--name"}},
            "name": "",
        }
        argv = _argv_for("neurag", "del", args)
        assert "--name" not in argv

    def test_unknown_tool_raises(self):
        from gray_matter.webgui import _argv_for
        with pytest.raises(ValueError, match="sconosciuto"):
            _argv_for("nope", "x", {})


# ---------------------------------------------------------------------------
# _say
# ---------------------------------------------------------------------------

class TestSay:
    def test_stdout_none_does_not_crash(self):
        from gray_matter.webgui import _say
        with patch("gray_matter.webgui.sys") as mock_sys:
            mock_sys.stdout = None
            _say("should not crash")

    def test_prints_to_stdout(self, capsys):
        from gray_matter.webgui import _say
        _say("hello")
        captured = capsys.readouterr()
        assert "hello" in captured.out


# ---------------------------------------------------------------------------
# _gm_version
# ---------------------------------------------------------------------------

class TestGmVersion:
    def test_returns_version_string(self):
        from gray_matter.webgui import _gm_version
        v = _gm_version()
        assert isinstance(v, str)
        assert v != ""


# ---------------------------------------------------------------------------
# Icon resolution in main()
# ---------------------------------------------------------------------------

class TestIconResolution:
    def test_icon_resolves_to_existing_ico(self):
        """On this machine, gray-matter.ico exists — main() should find it."""
        from gray_matter.webgui import Path
        ico = Path(__file__).resolve().parent.parent / "assets" / "gray-matter.ico"
        # The actual resolution inside main() uses Path(__file__).parent / "assets"
        # where __file__ is the webgui.py path
        from gray_matter import webgui
        real_ico = Path(webgui.__file__).parent / "assets" / "gray-matter.ico"
        assert real_ico.is_file(), "gray-matter.ico not found alongside webgui.py"
        assert real_ico.suffix == ".ico"

    def test_icon_not_injected_when_module_has_no_assets(self, tmp_path):
        """When webgui.py lives in a dir with no assets/, icon is skipped."""
        captured = {}
        def fake_start(**kwargs):
            captured.update(kwargs)
        fake_webview = MagicMock()
        fake_webview.start = fake_start
        fake_webview.create_window.return_value = MagicMock()

        # Create a fake webgui.py in an empty dir (no assets/)
        fake_dir = tmp_path / "gray_matter"
        fake_dir.mkdir()
        fake_webgui = fake_dir / "webgui.py"
        fake_webgui.write_text('pass')

        with patch.dict("sys.modules", {"webview": fake_webview}):
            # Point the module's __file__ to our fake location
            import gray_matter.webgui as wg
            orig_file = wg.__file__
            try:
                wg.__file__ = str(fake_webgui)
                from gray_matter.webgui import main
                with patch.dict(os.environ, {"GM_GUI_SELFTEST": "1"}):
                    main()
            finally:
                wg.__file__ = orig_file

        assert "icon" not in captured


# ---------------------------------------------------------------------------
# _HTML existence
# ---------------------------------------------------------------------------

class TestHtmlExists:
    def test_webgui_html_is_bundled(self):
        from gray_matter.webgui import _HTML
        assert _HTML.exists(), f"webgui.html not found at {_HTML}"
        content = _HTML.read_text(encoding="utf-8")
        assert "Gray Matter" in content
