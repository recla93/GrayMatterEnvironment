"""`gray-matter gui` — unified Tkinter control center for the trio.

One window, a collapsible panel per tool (Orchestrator/GM, Vault/NeuRAG,
Memory/Neuron). Reuses Neuron's dark theme and compacts it: each panel is a row
of buttons that run the existing console scripts and stream output. Tkinter is
stdlib (no dependency); on a headless box it prints a hint and exits.
"""
from __future__ import annotations

import queue
import subprocess
import threading
import tkinter as tk

__all__ = ["main"]

# Dark palette — shared with Neuron's Control Center (tokyo-night).
_BG = "#1a1b26"; _SURFACE = "#24283b"; _HOVER = "#414868"; _ACCENT = "#7aa2f7"
_FG = "#c0caf5"; _OUT_BG = "#16161e"; _FONT = "Segoe UI"


class _Section(tk.Frame):
    """A collapsible titled panel with a row of command buttons."""

    def __init__(self, parent, title, run, buttons):
        super().__init__(parent, bg=_BG)
        self._run, self._title, self._open = run, title, True
        self._head = tk.Label(self, text=f"▾  {title}", bg=_SURFACE, fg=_ACCENT,
                              font=(_FONT, 11, "bold"), anchor="w", padx=10, pady=6)
        self._head.pack(fill="x")
        self._head.bind("<Button-1>", self._toggle)
        self._body = tk.Frame(self, bg=_BG)
        self._body.pack(fill="x")
        for label, argv, needs in buttons:
            tk.Button(self._body, text=label, bg=_SURFACE, fg=_FG, bd=0,
                      activebackground=_HOVER, activeforeground=_FG,
                      font=(_FONT, 9), padx=8, pady=4,
                      command=lambda l=label, a=argv, n=needs: run(l, a, n)
                      ).pack(side="left", padx=4, pady=6)

    def _toggle(self, _e=None):
        self._open = not self._open
        if self._open:
            self._body.pack(fill="x"); self._head.config(text=f"▾  {self._title}")
        else:
            self._body.forget(); self._head.config(text=f"▸  {self._title}")


class _App:
    def __init__(self, root):
        self.root = root
        root.title("Gray Matter — Control Center")
        root.configure(bg=_BG)
        root.geometry("780x580")
        tk.Label(root, text="Gray Matter", bg=_BG, fg=_ACCENT,
                 font=(_FONT, 16, "bold"), pady=8).pack(fill="x")

        panels = tk.Frame(root, bg=_BG)
        panels.pack(fill="x", padx=8)
        _Section(panels, "Orchestrator (Gray-Matter)", self._run, [
            ("Status", ["gray-matter", "status"], None),
            ("Start", ["gray-matter", "start"], None),
            ("Collaborate all", ["gray-matter", "mode", "collaborate"], None),
            ("Separate all", ["gray-matter", "mode", "separate"], None),
        ]).pack(fill="x", pady=4)
        _Section(panels, "Vault (NeuRAG)", self._run, [
            ("Status", ["neurag", "status"], None),
            ("Tree", ["neurag", "tree"], None),
            ("Query…", ["neurag", "query"], "prompt"),
            ("Preview chunks…", ["neurag", "chunk"], "folder"),
            ("Import YAML…", ["neurag", "import"], "file"),
        ]).pack(fill="x", pady=4)
        _Section(panels, "Memory (Neuron)", self._run, [
            ("Open Neuron Control Center", ["neuron", "gui"], "detach"),
        ]).pack(fill="x", pady=4)

        self.out = tk.Text(root, bg=_OUT_BG, fg=_FG, insertbackground=_FG,
                           font=("Consolas", 9), wrap="word", height=14, bd=0)
        self.out.pack(fill="both", expand=True, padx=8, pady=8)
        self._q: queue.Queue = queue.Queue()
        root.after(120, self._drain)

    def _log(self, text):
        self.out.insert("end", text + "\n"); self.out.see("end")

    def _run(self, label, argv, needs):
        if needs == "prompt":
            from tkinter import simpledialog
            val = simpledialog.askstring(label, "Query:", parent=self.root)
            if not val:
                return
            argv = argv + [val]
        elif needs == "folder":
            from tkinter import filedialog
            d = filedialog.askdirectory()
            if not d:
                return
            argv = argv + [d]
        elif needs == "file":
            from tkinter import filedialog
            f = filedialog.askopenfilename(filetypes=[("YAML", "*.yaml *.yml"), ("All", "*.*")])
            if not f:
                return
            argv = argv + [f]
        elif needs == "detach":
            try:
                subprocess.Popen(argv)
                self._log(f"$ {' '.join(argv)}  (launched)")
            except Exception as e:  # noqa: BLE001
                self._log(f"! {e}")
            return
        self._log(f"$ {' '.join(argv)}")
        threading.Thread(target=self._exec, args=(argv,), daemon=True).start()

    def _exec(self, argv):
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
            self._q.put(((p.stdout or "") + (p.stderr or "")).rstrip() or "(no output)")
        except Exception as e:  # noqa: BLE001
            self._q.put(f"! {e}")

    def _drain(self):
        try:
            while True:
                self._log(self._q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(150, self._drain)


def main(argv=None) -> int:
    try:
        import tkinter  # noqa: F401 — availability check
    except Exception:
        print("Tkinter unavailable. Use the CLI instead: gray-matter status")
        return 1
    root = tk.Tk()
    _App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
