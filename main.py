# clipbeat.py
"""ClipBeat – cross‑platform clipboard cycler (Tkinter GUI).

Patch 2025‑07‑15 (c) – **current‑item highlight**
------------------------------------------------
* Adds a **yellow highlight** behind the line that was just copied so you
  always see which cue you’re on.
* Works even after you edit the text; highlight updates on every step.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from threading import Thread
from typing import Callable

# --------------------------------------------------------------
# Guard – Tkinter must be present
# --------------------------------------------------------------
try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:
    print("Tkinter is not available; install it and rerun.")
    sys.exit(1)

# --------------------------------------------------------------
# Optional global hot‑key backend – prefer `keyboard`, then `pynput`
# --------------------------------------------------------------
try:
    import keyboard  # type: ignore
    _GLOBAL_HOOK_BACKEND = "keyboard"
except ImportError:
    keyboard = None  # type: ignore
    _GLOBAL_HOOK_BACKEND = "none"

try:
    from pynput import keyboard as pynput_kb  # type: ignore
except ImportError:  # pragma: no cover – optional dependency
    pynput_kb = None  # type: ignore
    if _GLOBAL_HOOK_BACKEND != "keyboard":
        _GLOBAL_HOOK_BACKEND = "none"

APP_NAME = "ClipBeat"
DEFAULT_HOTKEYS = {
    "next": "ctrl+shift+alt+right",
    "prev": "ctrl+shift+alt+left",
}
CONFIG_PATH = Path(os.getenv("APPDATA") or Path.home() / ".config") / f"{APP_NAME.lower()}_config.json"


# ---------------------------------------------------------------------------
# Tk‑safe call from a background thread
# ---------------------------------------------------------------------------

def tk_safe(func: Callable, *args, **kwargs):
    root = tk._default_root  # type: ignore[attr-defined]
    if root:
        root.after(0, lambda: func(*args, **kwargs))


# ---------------------------------------------------------------------------
# Helper: clear all existing hot‑keys in a version‑agnostic way
# ---------------------------------------------------------------------------

def _reset_keyboard_hotkeys():  # only used if backend == "keyboard"
    try:
        keyboard.clear_all_hotkeys()  # >=0.13.5
    except AttributeError:
        try:
            keyboard.remove_all_hotkeys()  # older versions
        except AttributeError:
            try:
                keyboard.unhook_all_hotkeys()  # very old versions
            except Exception:  # pylint: disable=broad-except
                pass


class ClipBeatApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("500x350")

        # -------- state --------
        self.hotkeys: dict[str, str] = DEFAULT_HOTKEYS.copy()
        self._load_settings()
        self.items: list[str] = []
        self.line_map: list[int] = []  # map item index → Text line number
        self.index: int = 0  # pointer to next item to be copied

        # -------- UI --------
        self._build_widgets()
        self._bind_local_shortcuts()
        self._register_global_hooks()

    # ------------------------------------------------------------------
    # UI build
    # ------------------------------------------------------------------
    def _build_widgets(self) -> None:
        topbar = ttk.Frame(self)
        topbar.pack(fill="x")
        ttk.Button(topbar, text="\u2699", width=3, command=self._open_settings).pack(side="right", padx=5, pady=5)

        self.textbox = tk.Text(self, wrap="none", height=10)
        self.textbox.pack(fill="both", expand=True, padx=10)
        self.textbox.focus_set()
        self.textbox.tag_configure("current_item", background="#ffffaa")

        nav = ttk.Frame(self)
        nav.pack(fill="x", pady=5)
        ttk.Button(nav, text="◀", width=5, command=self.prev_item).pack(side="left", padx=(0, 5))
        self.index_lbl = ttk.Label(nav, text="0 / 0")
        self.index_lbl.pack(side="left")
        ttk.Button(nav, text="▶", width=5, command=self.next_item).pack(side="left", padx=5)

    # ------------------------------------------------------------------
    # Local shortcuts
    # ------------------------------------------------------------------
    def _bind_local_shortcuts(self):
        self.bind("<Right>", lambda _: self.next_item())
        self.bind("<Left>", lambda _: self.prev_item())

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------
    def _refresh_items(self):
        raw = self.textbox.get("1.0", "end-1c").splitlines()
        self.items = []
        self.line_map = []
        for lineno, ln in enumerate(raw, start=1):
            if ln.strip():
                self.items.append(ln.strip())
                self.line_map.append(lineno)
        self.index = min(self.index, max(0, len(self.items) - 1))

    def _update_label(self):
        total = len(self.items)
        self.index_lbl.configure(text=f"{(self.index) % total + 1 if total else 0} / {total}")

    def _highlight_current(self):
        self.textbox.tag_remove("current_item", "1.0", "end")
        if not self.items:
            return
        cur_line = self.line_map[self.index]
        self.textbox.tag_add("current_item", f"{cur_line}.0", f"{cur_line}.end")
        self.textbox.see(f"{cur_line}.0")  # ensure visible

    def _copy_current(self):
        if self.items:
            self.clipboard_clear()
            self.clipboard_append(self.items[self.index])
            self.update()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def next_item(self, *_):
        self._refresh_items()
        if not self.items:
            return
        self._highlight_current()
        self._copy_current()
        self._update_label()
        self.index = (self.index + 1) % len(self.items)

    def prev_item(self, *_):
        self._refresh_items()
        if not self.items:
            return
        self.index = (self.index - 1) % len(self.items)
        self._highlight_current()
        self._copy_current()
        self._update_label()

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------
    def _open_settings(self):
        SettingsDialog(self)

    def _load_settings(self):
        if CONFIG_PATH.exists():
            try:
                self.hotkeys.update(json.loads(CONFIG_PATH.read_text()).get("hotkeys", {}))
            except Exception as exc:  # pylint: disable=broad-except
                print(f"Warning: could not read settings – {exc}")

    def _save_settings(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps({"hotkeys": self.hotkeys}, indent=2))

    # ------------------------------------------------------------------
    # Global hot‑keys & paste detection
    # ------------------------------------------------------------------
    def _register_global_hooks(self):
        if _GLOBAL_HOOK_BACKEND == "keyboard":
            _reset_keyboard_hotkeys()
            for action, combo in self.hotkeys.items():
                try:
                    keyboard.add_hotkey(
                        combo,
                        lambda a=action: tk_safe(self.next_item if a == "next" else self.prev_item),
                    )
                except ValueError as exc:
                    messagebox.showerror("Hot‑key error", f"Could not bind {combo}: {exc}")
            keyboard.add_hotkey("ctrl+v", lambda: tk_safe(self.next_item), suppress=False)
        elif _GLOBAL_HOOK_BACKEND == "pynput" and pynput_kb is not None:
            def listener():
                with pynput_kb.GlobalHotKeys({"<ctrl>+v": lambda: tk_safe(self.next_item)}) as h:
                    h.join()
            Thread(target=listener, daemon=True).start()

    def on_settings_saved(self, new_hotkeys: dict[str, str]):
        self.hotkeys = new_hotkeys
        self._save_settings()
        self._register_global_hooks()


class SettingsDialog(tk.Toplevel):
    def __init__(self, master: "ClipBeatApp"):
        super().__init__(master)
        self.master_app = master
        self.title("Settings – Hot‑keys")
        self.resizable(False, False)
        self.geometry("300x160")
        self.transient(master)
        self.grab_set()

        self.next_var = tk.StringVar(value=master.hotkeys.get("next", ""))
        self.prev_var = tk.StringVar(value=master.hotkeys.get("prev", ""))

        ttk.Label(self, text="Next item global hot‑key:").pack(anchor="w", padx=10, pady=(10, 0))
        ttk.Entry(self, textvariable=self.next_var).pack(fill="x", padx=10)
        ttk.Label(self, text="Previous item global hot‑key:").pack(anchor="w", padx=10, pady=(10, 5))
        ttk.Entry(self, textvariable=self.prev_var).pack(fill="x", padx=10)

        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=10)
        ttk.Button(btns, text="Save", command=self._save).pack(side="right", padx=(0, 5))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")

    def _save(self):
        self.master_app.on_settings_saved({
            "next": self.next_var.get().strip(),
            "prev": self.prev_var.get().strip(),
        })
        self.destroy()


def main() -> None:
    ClipBeatApp().mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
