"""Ritirato: la vecchia GUI Tkinter è sostituita dal control center web.

Il modulo resta solo perché vecchi shortcut/launcher importano
``gray_matter.gui:main``. Qualunque strada porti qui apre la GUI vera
(:mod:`gray_matter.webgui`): una sola GUI, niente doppioni.
"""
from __future__ import annotations

from gray_matter.webgui import main  # noqa: F401  — unico entry point GUI

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
