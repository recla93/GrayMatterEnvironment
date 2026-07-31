"""Icona desktop per il control center — cross-OS, best-effort, idempotente.

Copia tool-local (keep-in-sync con neuron/shortcut.py e neurag/shortcut.py):
serve a Gray Matter, che è il tool principale. L'icona punta a `gray-matter gui`.

Se il marker esiste ma il file .lnk/.desktop è stato cancellato, ricrea l'icona.
Non solleva mai: un fallimento non deve impedire l'apertura della GUI.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def ensure_desktop_shortcut(tool: str, label: str, module_args: "list[str]",
                            description: str = "") -> bool:
    """Crea (una volta per installazione) un'icona desktop che apre ``<python>
    module_args`` (es. ``-m gray_matter.cli gui``). `tool` è la chiave per il marker.
    Se il marker esiste ma il file .lnk/.desktop è stato cancellato, ricrea.
    Ritorna True se l'icona c'è o è stata creata; False (silenzioso) altrimenti."""
    try:
        marker = Path(sys.executable).with_name(f".{tool}-gui-shortcut")
        shortcut_exists = _shortcut_file_exists(label)
        # The marker records WHAT was built, not just that something was. It
        # used to hold "1", so once a shortcut existed it was never revisited —
        # and the shortcuts already on disk had been created while
        # `assets/gray-matter.ico` was missing from the installed package, so
        # they fell back to the bare interpreter icon and kept it forever.
        # Shipping the asset fixes new installs; recording the recipe is what
        # fixes the ones already out there, on the next `gui`.
        recipe = f"icon={bool(_resolve_icon()) if os.name == 'nt' else False}"
        if marker.exists() and shortcut_exists:
            try:
                if marker.read_text(encoding="utf-8").strip() == recipe:
                    return True
            except OSError:
                pass                      # illeggibile: ricrea, non è un costo
        ok = (_windows_lnk(label, module_args, description) if os.name == "nt"
              else _mac_command(label, module_args) if sys.platform == "darwin"
              else _linux_desktop(label, module_args, description))
        if ok:
            try:
                marker.write_text(recipe, encoding="utf-8")
            except OSError:
                pass
        return ok
    except Exception:  # noqa: BLE001 — mai bloccare la GUI per un'icona
        return False


def _shortcut_file_exists(label: str) -> bool:
    """Check if the shortcut file actually exists on disk (not just the marker)."""
    if os.name == "nt":
        desk = os.environ.get("USERPROFILE", "") + "\\Desktop"
        return os.path.isfile(os.path.join(desk, f"{label}.lnk"))
    elif sys.platform == "darwin":
        return (Path.home() / "Desktop" / f"{label}.command").is_file()
    else:
        return ((Path.home() / ".local" / "share" / "applications"
                / f"{label.lower().replace(' ', '-')}.desktop").is_file()
                or (Path.home() / "Desktop" / f"{label}.desktop").is_file())


def _windows_lnk(label: str, module_args: "list[str]", description: str) -> bool:
    """.lnk vero via WScript.Shell (stesso approccio dell'installer GM). Target
    pythonw = nessun flash di console. Desktop via GetFolderPath (gestisce
    OneDrive redirect). If gray-matter.ico exists, it's used as the icon."""
    pyw = Path(sys.executable).with_name("pythonw.exe")
    target = str(pyw if pyw.exists() else Path(sys.executable))
    args = " ".join(module_args)
    workdir = str(Path(sys.executable).parent)

    # Resolve icon: prefer bundled gray-matter.ico, fallback to interpreter icon
    icon_path = _resolve_icon()

    ps = (
        "$d=[Environment]::GetFolderPath('Desktop'); if(-not $d){exit 1}\n"
        "$ws=New-Object -ComObject WScript.Shell\n"
        f"$sc=$ws.CreateShortcut((Join-Path $d '{label}.lnk'))\n"
        f"$sc.TargetPath='{target}'\n"
        f"$sc.Arguments='{args}'\n"
        f"$sc.WorkingDirectory='{workdir}'\n"
        f"$sc.Description='{description}'\n"
    )
    if icon_path:
        ps += f"$sc.IconLocation='{icon_path}'\n"
    ps += "$sc.Save()\n"
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, timeout=25, creationflags=_CREATE_NO_WINDOW)
    return r.returncode == 0


def _resolve_icon() -> str:
    """Find gray-matter.ico: look in the package assets dir, return path if found."""
    try:
        import gray_matter
        ico = Path(gray_matter.__file__).parent / "assets" / "gray-matter.ico"
        if ico.is_file():
            # Copy to a persistent location out of the user's way
            app_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "graymatter"
            app_dir.mkdir(parents=True, exist_ok=True)
            dest = app_dir / "gray-matter.ico"
            if not dest.exists():
                import shutil
                shutil.copy2(str(ico), str(dest))
            return str(dest)
    except Exception:  # noqa: BLE001
        pass
    return ""


def _linux_desktop(label: str, module_args: "list[str]", description: str) -> bool:
    """.desktop in ~/.local/share/applications e sul Desktop se c'è.
    ``Terminal=true`` così un eventuale bootstrap resta visibile."""
    exec_cmd = " ".join([sys.executable, *module_args])
    content = (
        "[Desktop Entry]\nType=Application\n"
        f"Name={label}\nComment={description}\nExec={exec_cmd}\n"
        "Terminal=true\nCategories=Utility;\n")
    slug = label.lower().replace(" ", "-")
    wrote = False
    apps = Path.home() / ".local" / "share" / "applications"
    try:
        apps.mkdir(parents=True, exist_ok=True)
        (apps / f"{slug}.desktop").write_text(content, encoding="utf-8")
        wrote = True
    except OSError:
        pass
    desk = Path.home() / "Desktop"
    if desk.is_dir():
        try:
            f = desk / f"{label}.desktop"
            f.write_text(content, encoding="utf-8")
            os.chmod(f, 0o755)
            wrote = True
        except OSError:
            pass
    return wrote


def _mac_command(label: str, module_args: "list[str]") -> bool:
    """.command doppio-clic sul Desktop (i .app veri servirebbero un bundle)."""
    desk = Path.home() / "Desktop"
    if not desk.is_dir():
        return False
    try:
        f = desk / f"{label}.command"
        f.write_text("#!/bin/sh\nexec " + " ".join(
            [f'"{sys.executable}"', *module_args]) + "\n", encoding="utf-8")
        os.chmod(f, 0o755)
        return True
    except OSError:
        return False
