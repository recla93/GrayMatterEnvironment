"""Tests for gray_matter.shortcut — icon resolution, idempotency, .lnk creation."""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# _windows_lnk
# ---------------------------------------------------------------------------

class TestWindowsLnk:
    """_windows_lnk shells out to PowerShell to create a real .lnk."""

    @patch("gray_matter.shortcut.subprocess.run")
    def test_uses_icon_when_ico_exists(self, mock_run, tmp_path):
        """When gray-matter.ico exists, IconLocation is set in the PS script."""
        mock_run.return_value = MagicMock(returncode=0)
        # Fake the gray_matter package location so the .ico lookup finds a file
        fake_ico = tmp_path / "gray-matter.ico"
        fake_ico.write_bytes(b"\x00\x00\x01\x00")  # minimal ICO header

        fake_pkg = tmp_path / "gray_matter"
        fake_pkg.mkdir()
        fake_assets = fake_pkg / "assets"
        fake_assets.mkdir()
        (fake_assets / "gray-matter.ico").write_bytes(b"\x00\x00\x01\x00")

        with patch.dict("sys.modules", {
            "gray_matter": MagicMock(__file__=str(fake_pkg / "__init__.py")),
        }):
            from gray_matter.shortcut import _windows_lnk
            result = _windows_lnk("Test Label", ["-m", "test"], "desc")

        assert result is True
        call_args = mock_run.call_args
        ps_script = call_args[0][0][-1]  # last arg to powershell -Command
        assert "IconLocation=" in ps_script
        assert "gray-matter.ico" in ps_script

    @patch("gray_matter.shortcut.subprocess.run")
    def test_no_icon_when_ico_missing(self, mock_run):
        """When gray-matter.ico doesn't exist, no IconLocation is injected."""
        mock_run.return_value = MagicMock(returncode=0)

        with patch.dict("sys.modules", {
            "gray_matter": MagicMock(__file__=None),
        }):
            from gray_matter.shortcut import _windows_lnk
            result = _windows_lnk("Test", ["-m", "x"], "")

        assert result is True
        ps_script = mock_run.call_args[0][0][-1]
        assert "IconLocation=" not in ps_script

    @patch("gray_matter.shortcut.subprocess.run")
    def test_returns_false_on_powershell_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr=b"err")
        with patch.dict("sys.modules", {
            "gray_matter": MagicMock(__file__=None),
        }):
            from gray_matter.shortcut import _windows_lnk
            assert _windows_lnk("X", ["-m", "x"], "") is False

    @patch("gray_matter.shortcut.subprocess.run")
    def test_target_uses_pythonw_when_available(self, mock_run, tmp_path):
        """pythonw.exe is preferred over python.exe as target."""
        mock_run.return_value = MagicMock(returncode=0)
        fake_pyw = tmp_path / "pythonw.exe"
        fake_pyw.write_text("")

        from gray_matter.shortcut import _windows_lnk
        with patch("gray_matter.shortcut.sys") as mock_sys:
            mock_sys.executable = str(tmp_path / "python.exe")
            # Path(sys.executable).with_name("pythonw.exe") should find the fake
            with patch.object(Path, "with_name", return_value=fake_pyw):
                _windows_lnk("T", ["-m", "t"], "")

        ps_script = mock_run.call_args[0][0][-1]
        assert "pythonw.exe" in ps_script


# ---------------------------------------------------------------------------
# ensure_desktop_shortcut
# ---------------------------------------------------------------------------

class TestEnsureDesktopShortcut:
    """Idempotency via marker file."""

    @patch("gray_matter.shortcut._windows_lnk", return_value=True)
    def test_creates_shortcut_when_no_marker(self, mock_lnk, tmp_path):
        marker = tmp_path / ".test-tool-gui-shortcut"
        assert not marker.exists()

        with patch("gray_matter.shortcut.sys") as mock_sys:
            mock_sys.executable = str(tmp_path / "python.exe")
            with patch("gray_matter.shortcut.os.name", "nt"):
                from gray_matter.shortcut import ensure_desktop_shortcut
                result = ensure_desktop_shortcut(
                    "test-tool", "Test", ["-m", "t"], "desc")

        assert result is True
        mock_lnk.assert_called_once()
        assert marker.exists()

    @patch("gray_matter.shortcut._windows_lnk")
    @patch("gray_matter.shortcut._shortcut_file_exists", return_value=True)
    def test_skips_when_marker_exists(self, mock_exists, mock_lnk, tmp_path):
        marker = tmp_path / ".mytool-gui-shortcut"
        marker.write_text("1")

        with patch("gray_matter.shortcut.sys") as mock_sys:
            mock_sys.executable = str(tmp_path / "python.exe")
            with patch("gray_matter.shortcut.os.name", "nt"):
                from gray_matter.shortcut import ensure_desktop_shortcut
                result = ensure_desktop_shortcut(
                    "mytool", "My", ["-m", "m"], "")

        assert result is True
        mock_lnk.assert_not_called()

    @patch("gray_matter.shortcut._windows_lnk", return_value=True)
    @patch("gray_matter.shortcut._shortcut_file_exists", return_value=False)
    def test_recreates_when_marker_exists_but_lnk_deleted(self, mock_exists, mock_lnk, tmp_path):
        """Marker present but .lnk deleted → recreate the shortcut."""
        marker = tmp_path / ".mytool-gui-shortcut"
        marker.write_text("1")

        with patch("gray_matter.shortcut.sys") as mock_sys:
            mock_sys.executable = str(tmp_path / "python.exe")
            with patch("gray_matter.shortcut.os.name", "nt"):
                from gray_matter.shortcut import ensure_desktop_shortcut
                result = ensure_desktop_shortcut(
                    "mytool", "My", ["-m", "m"], "")

        assert result is True
        mock_lnk.assert_called_once()

    def test_returns_false_on_exception(self):
        with patch("gray_matter.shortcut._windows_lnk", side_effect=OSError):
            with patch("gray_matter.shortcut.sys") as mock_sys:
                mock_sys.executable = "/nonexistent/python"
                from gray_matter.shortcut import ensure_desktop_shortcut
                result = ensure_desktop_shortcut(
                    "bad", "Bad", ["-m", "b"], "")
        assert result is False


# ---------------------------------------------------------------------------
# _linux_desktop
# ---------------------------------------------------------------------------

class TestLinuxDesktop:
    """_linux_desktop writes .desktop files."""

    def test_writes_to_applications_and_desktop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        desktop = tmp_path / "Desktop"
        desktop.mkdir()

        with patch("gray_matter.shortcut.sys") as mock_sys:
            mock_sys.executable = "/usr/bin/python3"
            from gray_matter.shortcut import _linux_desktop
            result = _linux_desktop("My App", ["-m", "my"], "My desc")

        assert result is True
        apps_file = tmp_path / ".local" / "share" / "applications" / "my-app.desktop"
        assert apps_file.exists()
        assert "My App" in apps_file.read_text()
        desk_file = desktop / "My App.desktop"
        assert desk_file.exists()
