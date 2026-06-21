from __future__ import annotations

import ctypes
import locale
import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageDraw, ImageTk

try:
    import winreg
except ImportError:  # pragma: no cover - only unavailable outside Windows
    winreg = None

from tkinterdnd2 import DND_FILES, TkinterDnD


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

ASSETS_DIR = ROOT / "assets"
SUPPORT_URL = "https://buymeacoffee.com/crocco"
WINDOWS_APP_ID = "Crocco.LastWarVSScanner"

from vsparser.pipeline import process_video  # noqa: E402
from vsparser.localization import tr  # noqa: E402
from vsparser.roster import (  # noqa: E402
    apply_roster_alias,
    available_roster_members,
    edit_result_name,
    load_roster,
    parse_member_list,
    save_roster,
)
from vsparser.export import write_row_exports  # noqa: E402
from vsparser.week_storage import iso_week, load_week, save_week, selectable_weeks  # noqa: E402


DISPLAY_COLUMNS = ("rank", "name", "points", "confidence", "issues")
HEADINGS = tuple(tr(value) for value in ("Rank", "Name", "Points", "Confidence", "Issues"))
COPY_COLUMN_COUNT = 3
COPY_HEADINGS = HEADINGS[:COPY_COLUMN_COUNT]
DAILY_SLOTS = tuple(f"Day {number}" for number in range(1, 7))
SLOTS = DAILY_SLOTS + ("Weekly Overall",)
PUSH_SUMMARY = "Push Days"
VIEW_SLOTS = SLOTS + (PUSH_SUMMARY,)
BASE_DPI = 96
FONT_FAMILY = "Inter"
TUTORIAL_MARKER = ".tutorial_alliance_members_v2_seen"


def should_show_first_launch_tip(data_dir: Path) -> bool:
    return not (data_dir / TUTORIAL_MARKER).exists()


def mark_first_launch_tip_seen(data_dir: Path) -> None:
    """Persist the tutorial state only after the callout was actually displayed."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / TUTORIAL_MARKER).touch(exist_ok=True)
    except OSError:
        pass


def configure_app_fonts(root: tk.Misc) -> None:
    for name in (
        "TkDefaultFont",
        "TkTextFont",
        "TkFixedFont",
        "TkMenuFont",
        "TkHeadingFont",
        "TkCaptionFont",
        "TkSmallCaptionFont",
        "TkIconFont",
        "TkTooltipFont",
    ):
        try:
            tkfont.nametofont(name, root=root).configure(family=FONT_FAMILY)
        except tk.TclError:
            pass


def resampled_photo(path: Path, size: tuple[int, int], master: tk.Misc) -> ImageTk.PhotoImage:
    with Image.open(path) as source:
        image = source.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(image, master=master)


def toggle_badge_photo(
    master: tk.Misc,
    fill: str,
    outline: str,
    check: str,
    selected: bool,
) -> ImageTk.PhotoImage:
    scale = 4
    size = 24
    image = Image.new("RGBA", (size * scale, size * scale))
    draw = ImageDraw.Draw(image)
    draw.ellipse(
        (scale, scale, (size - 1) * scale, (size - 1) * scale),
        fill=fill,
        outline=outline,
        width=scale,
    )
    if selected:
        points = [(6 * scale, 12 * scale), (10 * scale, 16 * scale), (18 * scale, 7 * scale)]
        width = 3 * scale
        draw.line(points, fill=check, width=width, joint="curve")
        radius = width // 2
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=check)
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(image, master=master)


def slot_label(slot: str) -> str:
    if slot.startswith("Day "):
        return tr("Day {number}", number=slot.removeprefix("Day "))
    return tr(slot)

try:
    locale.setlocale(locale.LC_NUMERIC, "")
except locale.Error:
    pass


def format_points(value: int | None) -> str:
    if value is None:
        return ""
    return locale.format_string("%d", value, grouping=True)


def aggregate_push_rows(rows: dict[str, list[dict]], push_days: dict[str, bool]) -> list[dict]:
    totals: dict[str, dict] = {}
    for slot in DAILY_SLOTS:
        if not push_days.get(slot, False):
            continue
        for row in rows.get(slot, []):
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            key = name.casefold()
            total = totals.setdefault(key, {"name": name, "points": 0})
            total["points"] += row.get("points") or 0

    ranked = sorted(totals.values(), key=lambda row: (-row["points"], row["name"].casefold()))
    return [
        {
            "rank": index,
            "name": row["name"],
            "points": row["points"],
            "confidence": 0,
            "issues": "",
        }
        for index, row in enumerate(ranked, start=1)
    ]


THEMES = {
    False: {
        "background": "#f3f3f3", "surface": "#ffffff", "field": "#ffffff",
        "text": "#1a1a1a", "muted": "#5f5f5f", "border": "#c7c7c7",
        "control_border": "#dedede",
        "select": "#0067c0", "select_text": "#ffffff",
        "warning": "#fff2cc", "error": "#ffd6d6",
    },
    True: {
        "background": "#202020", "surface": "#2b2b2b", "field": "#252525",
        "text": "#f2f2f2", "muted": "#b3b3b3", "border": "#555555",
        "control_border": "#414141",
        "select": "#4a9ee8", "select_text": "#ffffff",
        "warning": "#65531b", "error": "#672f35",
    },
}


class ProcessingCancelled(Exception):
    pass


class RoundedButton(tk.Canvas):
    def __init__(self, parent, text: str, width: int, command) -> None:
        super().__init__(parent, width=width, height=26, highlightthickness=0, cursor="hand2")
        self.command = command
        self.shape = self.create_polygon(
            10, 1, width - 10, 1, width - 1, 1, width - 1, 10,
            width - 1, 16, width - 1, 25, width - 10, 25, 10, 25,
            1, 25, 1, 16, 1, 10, 1, 1,
            smooth=True, splinesteps=24, width=1,
        )
        self.label = self.create_text(width / 2, 13, text=text, font=(FONT_FAMILY, 8))
        self.bind("<Button-1>", lambda _event: self.command())
        self.bind("<Enter>", lambda _event: self.configure(cursor="hand2"))
        self.apply_theme()

    def apply_theme(self) -> None:
        colors = THEMES[bool(self.winfo_toplevel().system_theme.dark)]
        self.configure(background=colors["surface"])
        self.itemconfigure(
            self.shape, fill=colors["field"], outline=colors["control_border"]
        )
        self.itemconfigure(self.label, fill=colors["text"])


class PushToggle(tk.Canvas):
    def __init__(self, parent, variable: tk.BooleanVar, command) -> None:
        super().__init__(parent, width=92, height=26, highlightthickness=0, cursor="hand2")
        self.variable = variable
        self.command = command
        self.hovered = False
        self.label = self.create_text(34, 13, text=tr("Push day"), font=(FONT_FAMILY, 9))
        self._badge_image: ImageTk.PhotoImage | None = None
        self.badge = self.create_image(80, 14)
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.apply_theme()

    def _toggle(self, _event=None) -> None:
        self.variable.set(not self.variable.get())
        self.apply_theme()
        self.command()

    def _enter(self, _event=None) -> None:
        self.hovered = True
        self.apply_theme()

    def _leave(self, _event=None) -> None:
        self.hovered = False
        self.apply_theme()

    def apply_theme(self) -> None:
        colors = THEMES[bool(self.winfo_toplevel().system_theme.dark)]
        selected = self.variable.get()
        self.configure(background=colors["surface"])
        self.itemconfigure(self.label, fill=colors["text"])
        self._badge_image = toggle_badge_photo(
            self,
            fill=colors["select"] if selected else colors["border"] if self.hovered else colors["field"],
            outline=colors["select"] if selected else colors["text"] if self.hovered else colors["control_border"],
            check=colors["select_text"],
            selected=selected,
        )
        self.itemconfigure(self.badge, image=self._badge_image)


class DropCard(tk.Canvas):
    def __init__(self, parent, slot: str, on_open, on_browse, on_clear, on_push=None) -> None:
        super().__init__(parent, height=104, highlightthickness=0, cursor="hand2")
        self.slot = slot
        self.filename = ""
        self.selected = False
        self._tooltip: tk.Toplevel | None = None
        self._shape: int | None = None
        self._on_open = on_open
        self.title = ttk.Label(self, text=slot_label(slot), font=(FONT_FAMILY, 10, "bold"), anchor="center")
        self.message = ttk.Label(self, text=tr("Drop MP4 here"), style="Muted.TLabel", anchor="center")
        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.browse = RoundedButton(self, text=tr("Browse"), width=54, command=on_browse)
        self.clear = RoundedButton(self, text="X", width=26, command=on_clear)
        self.push_var = tk.BooleanVar(value=False)
        self.push = PushToggle(
            self, variable=self.push_var, command=on_push,
        ) if on_push is not None else None
        self._windows = [
            self.create_window(0, 0, window=self.title),
            self.create_window(0, 0, window=self.message),
            self.create_window(0, 0, window=self.progress),
            self.create_window(0, 0, window=self.browse),
            self.create_window(0, 0, window=self.clear),
        ]
        if self.push is not None:
            self._windows.append(self.create_window(0, 0, window=self.push, anchor="se"))
        self.bind("<Configure>", self._layout)
        for widget in (self, self.title, self.message):
            widget.bind("<Button-1>", lambda _event: self._on_open())
            widget.bind("<Enter>", self._show_tooltip)
            widget.bind("<Leave>", self._hide_tooltip)

    def _rounded_rectangle(self, width: int, height: int, radius: int = 14) -> int:
        points = [
            radius, 1, width - radius, 1, width - 1, 1, width - 1, radius,
            width - 1, height - radius, width - 1, height - 1, width - radius, height - 1,
            radius, height - 1, 1, height - 1, 1, height - radius, 1, radius, 1, 1,
        ]
        return self.create_polygon(points, smooth=True, splinesteps=24, width=1)

    def _layout(self, _event=None) -> None:
        width, height = self.winfo_width(), self.winfo_height()
        if self._shape is not None:
            self.delete(self._shape)
        self._shape = self._rounded_rectangle(width, height)
        self.tag_lower(self._shape)
        self.coords(self._windows[0], width / 2, 31)
        self.coords(self._windows[1], width / 2, 57)
        if self.push is not None:
            progress_width = max(70, width - 130)
            self.coords(self._windows[2], 14 + progress_width / 2, 81)
            self.itemconfigure(self._windows[2], width=progress_width)
        else:
            self.coords(self._windows[2], width / 2, 81)
            self.itemconfigure(self._windows[2], width=max(70, width - 28))
        self.coords(self._windows[3], width - 66, 17)
        self.coords(self._windows[4], width - 17, 17)
        if self.push is not None:
            self.coords(self._windows[5], width - 10, height - 8)
        self.apply_theme()

    def apply_theme(self) -> None:
        colors = THEMES[bool(self.winfo_toplevel().system_theme.dark)]
        self.configure(background=colors["background"])
        if self._shape is not None:
            self.itemconfigure(
                self._shape,
                fill=colors["surface"],
                outline=colors["select"] if self.selected else colors["border"],
                width=3 if self.selected else 1,
            )
        self.title.configure(
            background=colors["surface"],
            foreground=colors["select"] if self.selected else colors["text"],
        )
        self.message.configure(background=colors["surface"])

    def set_selected(self, selected: bool) -> None:
        if self.selected != selected:
            self.selected = selected
            self.apply_theme()

    def show_state(
        self,
        message: str,
        filename: str = "",
        progress: float | None = None,
        browse: bool = True,
        clear: bool = True,
    ) -> None:
        self.filename = filename
        self.message.configure(text=message)
        self.itemconfigure(self._windows[2], state="hidden" if progress is None else "normal")
        self.itemconfigure(self._windows[3], state="normal" if browse else "hidden")
        self.itemconfigure(self._windows[4], state="normal" if clear else "hidden")
        if progress is not None:
            self.progress["value"] = progress

    def set_push_day(self, selected: bool) -> None:
        self.push_var.set(selected)
        if self.push is not None:
            self.push.apply_theme()

    def _show_tooltip(self, _event=None) -> None:
        if not self.filename or self._tooltip is not None:
            return
        self._tooltip = tk.Toplevel(self)
        self._tooltip.wm_overrideredirect(True)
        self._tooltip.wm_geometry(f"+{self.winfo_pointerx() + 12}+{self.winfo_pointery() + 12}")
        ttk.Label(self._tooltip, text=self.filename, padding=(8, 4), relief="solid").pack()
        self.winfo_toplevel().system_theme.theme_window(self._tooltip)

    def _hide_tooltip(self, _event=None) -> None:
        if self._tooltip is not None:
            self._tooltip.destroy()
            self._tooltip = None


class ActionCard(tk.Canvas):
    def __init__(self, parent, title: str, message: str, on_open) -> None:
        super().__init__(parent, height=104, highlightthickness=0, cursor="hand2")
        self._shape: int | None = None
        self.selected = False
        self.title = ttk.Label(self, text=title, font=(FONT_FAMILY, 10, "bold"), anchor="center")
        self.message = ttk.Label(self, text=message, style="Muted.TLabel", anchor="center")
        self._windows = [
            self.create_window(0, 0, window=self.title),
            self.create_window(0, 0, window=self.message),
        ]
        self.bind("<Configure>", self._layout)
        for widget in (self, self.title, self.message):
            widget.bind("<Button-1>", lambda _event: on_open())

    def _layout(self, _event=None) -> None:
        width, height = self.winfo_width(), self.winfo_height()
        if self._shape is not None:
            self.delete(self._shape)
        self._shape = DropCard._rounded_rectangle(self, width, height)
        self.tag_lower(self._shape)
        self.coords(self._windows[0], width / 2, 39)
        self.coords(self._windows[1], width / 2, 65)
        self.apply_theme()

    def apply_theme(self) -> None:
        colors = THEMES[bool(self.winfo_toplevel().system_theme.dark)]
        self.configure(background=colors["background"])
        if self._shape is not None:
            self.itemconfigure(
                self._shape,
                fill=colors["surface"],
                outline=colors["select"] if self.selected else colors["border"],
                width=3 if self.selected else 1,
            )
        self.title.configure(
            background=colors["surface"],
            foreground=colors["select"] if self.selected else colors["text"],
        )
        self.message.configure(background=colors["surface"])

    def set_selected(self, selected: bool) -> None:
        if self.selected != selected:
            self.selected = selected
            self.apply_theme()


class SupportButton(ttk.Label):
    def __init__(self, parent, command) -> None:
        self._light_image = resampled_photo(ASSETS_DIR / "white-button.png", (136, 38), parent)
        self._dark_image = resampled_photo(ASSETS_DIR / "black-button.png", (136, 38), parent)
        super().__init__(
            parent,
            cursor="hand2",
            takefocus=True,
        )
        self.bind("<Button-1>", command)
        self.bind("<Return>", command)
        self.bind("<space>", command)
        self.apply_theme()

    def apply_theme(self) -> None:
        dark = bool(self.winfo_toplevel().system_theme.dark)
        self.configure(image=self._dark_image if dark else self._light_image)


def system_uses_dark_theme() -> bool:
    if sys.platform != "win32" or winreg is None:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return not bool(value)
    except OSError:
        return False


def windows_system_color(index: int, fallback: str) -> str:
    if sys.platform != "win32":
        return fallback
    try:
        color = ctypes.windll.user32.GetSysColor(index)
    except (AttributeError, OSError):
        return fallback
    red = color & 0xFF
    green = (color >> 8) & 0xFF
    blue = (color >> 16) & 0xFF
    return f"#{red:02x}{green:02x}{blue:02x}"


def set_window_dark_mode(window: tk.Misc, dark: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        enabled = ctypes.c_int(int(dark))
        get_parent = ctypes.windll.user32.GetParent
        get_parent.argtypes = [ctypes.c_void_p]
        get_parent.restype = ctypes.c_void_p
        hwnd = get_parent(window.winfo_id())
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
            )
            if result == 0:
                break
    except (AttributeError, OSError, tk.TclError):
        pass


class SystemTheme:
    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.dark: bool | None = None
        self._apply_if_changed()
        root.after(1000, self._poll)

    def _apply_if_changed(self) -> None:
        dark = system_uses_dark_theme()
        colors = THEMES[dark]
        row_highlight = windows_system_color(13, colors["select"])
        row_highlight_text = windows_system_color(14, colors["select_text"])
        theme_state = (dark, row_highlight, row_highlight_text)
        if theme_state == getattr(self, "_theme_state", None):
            return
        self._theme_state = theme_state
        self.dark = dark
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=colors["background"], foreground=colors["text"])
        style.configure("TLabel", background=colors["background"], foreground=colors["text"])
        style.configure("Muted.TLabel", foreground=colors["muted"])
        style.configure("Link.TLabel", foreground=colors["select"], font=(FONT_FAMILY, 9, "underline"))
        style.configure("TButton", background=colors["surface"], bordercolor=colors["border"])
        style.map("TButton", background=[("active", colors["border"])])
        style.configure(
            "TScrollbar", background=colors["surface"],
            troughcolor=colors["background"], bordercolor=colors["border"],
        )
        style.configure("TSeparator", background=colors["border"])
        for name in ("TEntry", "TCombobox"):
            style.configure(name, fieldbackground=colors["field"], foreground=colors["text"])
        style.configure("TCombobox", arrowcolor=colors["text"])
        style.map(
            "TCombobox", fieldbackground=[("readonly", colors["field"])],
            foreground=[("readonly", colors["text"])],
            selectbackground=[("readonly", colors["field"])],
            selectforeground=[("readonly", colors["text"])],
            arrowcolor=[
                ("disabled", colors["muted"]),
                ("pressed", colors["select_text"]),
                ("active", colors["text"]),
                ("readonly", colors["text"]),
            ],
        )
        style.configure(
            "Treeview", background=colors["field"], fieldbackground=colors["field"],
            foreground=colors["text"], bordercolor=colors["border"],
        )
        style.map(
            "Treeview", background=[("selected", row_highlight)],
            foreground=[("selected", row_highlight_text)],
        )
        style.configure("Treeview.Heading", background=colors["surface"], foreground=colors["text"])
        style.map(
            "Treeview.Heading",
            background=[("pressed", colors["select"]), ("active", colors["border"])],
            foreground=[("pressed", colors["select_text"]), ("active", colors["text"])],
        )
        style.configure("TNotebook", background=colors["background"], bordercolor=colors["border"])
        style.layout("Tabless.TNotebook.Tab", [])
        style.configure("TNotebook.Tab", background=colors["surface"], foreground=colors["text"])
        style.map(
            "TNotebook.Tab",
            background=[("selected", colors["background"]), ("active", colors["border"])],
        )
        style.configure("TProgressbar", background=colors["select"], troughcolor=colors["surface"])
        self.root.option_add("*Canvas.background", colors["background"])
        self.root.option_add("*Listbox.background", colors["field"])
        self.root.option_add("*Listbox.foreground", colors["text"])
        self.root.option_add("*Listbox.selectBackground", colors["select"])
        self.root.option_add("*Listbox.selectForeground", colors["select_text"])
        self.theme_window(self.root)

    def theme_window(self, window: tk.Misc) -> None:
        colors = THEMES[bool(self.dark)]
        self._update_widgets(window, colors)

    def _update_widgets(self, widget: tk.Misc, colors: dict[str, str]) -> None:
        if isinstance(widget, (tk.Tk, tk.Toplevel)):
            widget.configure(background=colors["background"])
            set_window_dark_mode(widget, bool(self.dark))
        elif isinstance(widget, SupportButton):
            widget.apply_theme()
        elif isinstance(widget, (RoundedButton, PushToggle)):
            widget.apply_theme()
        elif isinstance(widget, (DropCard, ActionCard)):
            widget.apply_theme()
        elif isinstance(widget, tk.Canvas):
            widget.configure(background=colors["background"])
        elif isinstance(widget, tk.Listbox):
            widget.configure(
                background=colors["field"], foreground=colors["text"],
                selectbackground=colors["select"], selectforeground=colors["select_text"],
            )
        elif isinstance(widget, tk.Text):
            widget.configure(
                background=colors["field"], foreground=colors["text"],
                selectbackground=colors["select"], selectforeground=colors["select_text"],
                insertbackground=colors["text"],
            )
        elif isinstance(widget, ttk.Treeview):
            widget.tag_configure("non_member", background=colors["error"])
            widget.tag_configure("missing_member", background=colors["warning"])
        for child in widget.winfo_children():
            self._update_widgets(child, colors)

    def _poll(self) -> None:
        self._apply_if_changed()
        self.root.after(1000, self._poll)


def enable_per_monitor_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


def set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except (AttributeError, OSError):
        pass


def window_dpi(window: tk.Misc) -> int:
    if sys.platform == "win32":
        try:
            get_dpi = ctypes.windll.user32.GetDpiForWindow
            get_dpi.argtypes = [ctypes.c_void_p]
            get_dpi.restype = ctypes.c_uint
            dpi = int(get_dpi(window.winfo_id()))
            if dpi:
                return dpi
        except (AttributeError, OSError, tk.TclError):
            pass
    return round(float(window.winfo_fpixels("1i")))


def set_scaled_window_size(
    window: tk.Misc,
    width: int,
    height: int,
    min_width: int,
    min_height: int,
) -> None:
    scale = window_dpi(window) / BASE_DPI
    window.geometry(f"{round(width * scale)}x{round(height * scale)}")
    window.minsize(round(min_width * scale), round(min_height * scale))


class DpiMonitor:
    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.dpi = window_dpi(root)
        self._pending: str | None = None
        self._apply_scaling()
        root.bind("<Configure>", self._schedule_check, add="+")

    def _apply_scaling(self) -> None:
        self.root.tk.call("tk", "scaling", self.dpi / 72)

    def _schedule_check(self, _event=None) -> None:
        if self._pending is not None:
            self.root.after_cancel(self._pending)
        self._pending = self.root.after(150, self._check_display)

    def _check_display(self) -> None:
        self._pending = None
        dpi = window_dpi(self.root)
        if dpi != self.dpi:
            self.dpi = dpi
            self._apply_scaling()


class MemberEditor:
    def __init__(self, parent: tk.Misc, roster_path: Path, on_saved) -> None:
        self.roster_path = roster_path
        self.on_saved = on_saved
        self.system_theme = parent.winfo_toplevel().system_theme
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(tr("Alliance Members"))
        self.system_theme.theme_window(self.dialog)
        set_scaled_window_size(self.dialog, 620, 560, 480, 340)
        self.dialog.transient(parent)

        try:
            self.members = load_roster(roster_path)
        except (OSError, ValueError, TypeError) as error:
            self.dialog.destroy()
            messagebox.showerror(tr("Could not open members"), str(error), parent=parent)
            return
        self.name_sort_descending: bool | None = None

        frame = ttk.Frame(self.dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=tr("Alliance members"), font=(FONT_FAMILY, 14, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text=tr("Add members individually or in a batch. Double-click a name to edit it in place."),
            wraplength=570,
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 10))

        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text=tr("Add Multiple Entries"), command=self._add_multiple_entries).pack(side="left")
        self.remove_all_button = ttk.Button(toolbar, text=tr("Remove All"), command=self._remove_all)
        self.remove_all_button.pack(side="right")

        search_row = ttk.Frame(frame)
        search_row.pack(fill="x", pady=(0, 8))
        ttk.Label(search_row, text=tr("Search")).pack(side="left", padx=(0, 8))
        self.search_query = tk.StringVar()
        search_entry = ttk.Entry(search_row, textvariable=self.search_query)
        search_entry.pack(side="left", fill="x", expand=True)
        self.search_query.trace_add("write", lambda *_args: self._render_rows())

        table_frame = ttk.Frame(frame, relief="solid", borderwidth=1)
        table_frame.pack(fill="both", expand=True)
        header = ttk.Frame(table_frame, padding=(8, 6))
        header.pack(fill="x")
        ttk.Label(header, text="#", width=4, font=(FONT_FAMILY, 9, "bold")).pack(side="left")
        self.name_header = ttk.Label(header, text=tr("Name"), font=(FONT_FAMILY, 9, "bold"), cursor="hand2")
        self.name_header.pack(side="left")
        self.name_header.bind("<Button-1>", lambda _event: self._sort_members())
        ttk.Label(header, text=tr("Actions"), font=(FONT_FAMILY, 9, "bold")).pack(side="right", padx=(0, 45))

        self.canvas = tk.Canvas(table_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.canvas.yview)
        self.rows = ttk.Frame(self.canvas)
        self.rows.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.rows, anchor="nw")
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.canvas_window, width=event.width))
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(12, 0))
        ttk.Button(controls, text=tr("Cancel"), command=self.dialog.destroy).pack(side="right")
        ttk.Button(controls, text=tr("Save Members"), command=self._save).pack(side="right", padx=(0, 8))

        self.dialog.bind("<MouseWheel>", self._scroll_members, add="+")
        self.dialog.bind("<Button-4>", self._scroll_members, add="+")
        self.dialog.bind("<Button-5>", self._scroll_members, add="+")
        self._render_rows()

    def _render_rows(self) -> None:
        for child in self.rows.winfo_children():
            child.destroy()
        self.remove_all_button.configure(state="normal" if self.members else "disabled")
        add_row = ttk.Frame(self.rows, padding=(8, 4))
        add_row.pack(fill="x")
        add_button = ttk.Button(add_row, text="+", width=3, command=self._begin_add_member)
        add_button.pack(side="left", padx=(0, 8))
        add_label = ttk.Label(add_row, text=tr("Add member"), cursor="hand2")
        add_label.pack(side="left", fill="x", expand=True)
        add_label.bind("<Button-1>", lambda _event: self._begin_add_member())
        ttk.Separator(self.rows).pack(fill="x")
        if not self.members:
            ttk.Label(
                self.rows, text=tr("No members yet. Add one or add multiple entries to begin."),
                style="Muted.TLabel", padding=12,
            ).pack()
            return
        members = list(self.members.items())
        if self.name_sort_descending is not None:
            members = sorted(
                members, key=lambda item: item[0].casefold(), reverse=self.name_sort_descending,
            )
        query = self.search_query.get().strip().casefold()
        if query:
            members = [
                (name, aliases) for name, aliases in members
                if query in name.casefold() or any(query in alias.casefold() for alias in aliases)
            ]
        if not members:
            ttk.Label(
                self.rows, text=tr("No members match your search."), style="Muted.TLabel", padding=12,
            ).pack()
            return
        for number, (name, aliases) in enumerate(members, start=1):
            row = ttk.Frame(self.rows, padding=(8, 4))
            row.pack(fill="x")
            ttk.Label(row, text=str(number), width=4).pack(side="left")
            label = ttk.Label(row, text=name, cursor="xterm")
            label.pack(side="left", fill="x", expand=True)
            label.bind("<Double-Button-1>", lambda _event, current=name, widget=label: self._edit_name(current, widget))
            ttk.Button(row, text=tr("Delete"), command=lambda current=name: self._delete(current)).pack(side="right")
            alias_text = tr("Other Names ({count})", count=len(aliases)) if aliases else tr("Other Names")
            ttk.Button(row, text=alias_text, command=lambda current=name: self._edit_aliases(current)).pack(
                side="right", padx=(0, 6)
            )
            ttk.Separator(self.rows).pack(fill="x")

    def _begin_add_member(self) -> None:
        add_row = self.rows.winfo_children()[0]
        for child in add_row.winfo_children():
            child.destroy()
        entry = ttk.Entry(add_row)
        entry.pack(side="left", fill="x", expand=True)

        def add_member(_event=None):
            name = entry.get().strip()
            if not name:
                self._render_rows()
                return "break"
            if any(self._name_key(existing) == self._name_key(name) for existing in self.members):
                messagebox.showwarning(
                    tr("Duplicate member"), tr('"{name}" is already in the member list.', name=name), parent=self.dialog,
                )
                entry.focus_set()
                return "break"
            self.members[name] = []
            self._render_rows()
            return "break"

        ttk.Button(add_row, text=tr("Add"), command=add_member).pack(side="left", padx=(6, 0))
        entry.bind("<Return>", add_member)
        entry.bind("<Escape>", lambda _event: self._render_rows())
        entry.focus_set()

    def _scroll_members(self, event):
        pointer_x = self.dialog.winfo_pointerx()
        pointer_y = self.dialog.winfo_pointery()
        canvas_x = self.canvas.winfo_rootx()
        canvas_y = self.canvas.winfo_rooty()
        if not (
            canvas_x <= pointer_x < canvas_x + self.canvas.winfo_width()
            and canvas_y <= pointer_y < canvas_y + self.canvas.winfo_height()
        ):
            return None
        if getattr(event, "num", None) == 4:
            units = -1
        elif getattr(event, "num", None) == 5:
            units = 1
        else:
            delta = getattr(event, "delta", 0)
            units = -1 if delta > 0 else 1
        self.canvas.yview_scroll(units, "units")
        return "break"

    def _add_multiple_entries(self) -> None:
        popup = tk.Toplevel(self.dialog)
        popup.title(tr("Add Multiple Entries"))
        set_scaled_window_size(popup, 400, 320, 320, 240)
        popup.transient(self.dialog)

        frame = ttk.Frame(popup, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=tr("Add multiple members"), font=(FONT_FAMILY, 11, "bold")).pack(anchor="w")
        ttk.Label(
            frame, text=tr("Paste one member per line. Existing names and duplicate lines are skipped."),
            style="Muted.TLabel", wraplength=360,
        ).pack(anchor="w", pady=(2, 8))

        editor = tk.Text(frame, wrap="none", undo=True, font=(FONT_FAMILY, 10), height=8)
        editor.pack(fill="both", expand=True)

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(10, 0))
        ttk.Button(controls, text=tr("Cancel"), command=popup.destroy).pack(side="right")

        def add_entries() -> None:
            existing = {self._name_key(name) for name in self.members}
            for name in parse_member_list(editor.get("1.0", "end-1c")):
                key = self._name_key(name)
                if key and key not in existing:
                    self.members[name] = []
                    existing.add(key)
            popup.destroy()
            self._render_rows()

        ttk.Button(controls, text=tr("Add Members"), command=add_entries).pack(side="right", padx=(0, 8))
        self.system_theme.theme_window(popup)
        editor.focus_set()

    def _sort_members(self) -> None:
        if self.name_sort_descending is None:
            self.name_sort_descending = False
        else:
            self.name_sort_descending = not self.name_sort_descending
        self.name_header.configure(text=tr("Name (Z-A)") if self.name_sort_descending else tr("Name (A-Z)"))
        self._render_rows()

    @staticmethod
    def _name_key(name: str) -> str:
        return "".join(character.casefold() for character in name if character.isalnum())

    def _edit_name(self, old_name: str, label: ttk.Label) -> None:
        entry = ttk.Entry(label.master)
        entry.insert(0, old_name)
        entry.place(in_=label, x=0, y=0, relwidth=1, relheight=1)
        entry.focus_set()
        entry.select_range(0, "end")

        def finish(_event=None) -> None:
            new_name = entry.get().strip()
            if not new_name or new_name == old_name:
                self._render_rows()
                return
            if any(self._name_key(name) == self._name_key(new_name) for name in self.members if name != old_name):
                messagebox.showwarning(tr("Duplicate member"), tr('"{name}" is already in the member list.', name=new_name), parent=self.dialog)
                entry.focus_set()
                return
            self.members = {
                (new_name if name == old_name else name): aliases for name, aliases in self.members.items()
            }
            self._render_rows()

        entry.bind("<Return>", finish)
        entry.bind("<Escape>", lambda _event: self._render_rows())
        entry.bind("<FocusOut>", finish)

    def _delete(self, name: str) -> None:
        del self.members[name]
        self._render_rows()

    def _remove_all(self) -> None:
        if not self.members:
            return
        if not messagebox.askokcancel(
            tr("Remove all members"),
            tr("Remove all alliance members? This cannot be undone after saving."),
            parent=self.dialog,
        ):
            return
        self.members.clear()
        self._render_rows()

    def _edit_aliases(self, name: str) -> None:
        popup = tk.Toplevel(self.dialog)
        popup.title(tr("Other Names - {name}", name=name))
        set_scaled_window_size(popup, 420, 360, 340, 280)
        popup.transient(self.dialog)
        frame = ttk.Frame(popup, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=tr("Other names for {name}", name=name), font=(FONT_FAMILY, 11, "bold")).pack(anchor="w")
        ttk.Label(frame, text=tr("Add spelling or OCR variations for this member."), style="Muted.TLabel").pack(
            anchor="w", pady=(2, 8)
        )

        aliases = list(self.members[name])
        add_row = ttk.Frame(frame)
        add_row.pack(fill="x", pady=(0, 8))
        alias_entry = ttk.Entry(add_row)
        alias_entry.pack(side="left", fill="x", expand=True)

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True)
        alias_list = tk.Listbox(list_frame, activestyle="dotbox", font=(FONT_FAMILY, 10))
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=alias_list.yview)
        alias_list.configure(yscrollcommand=scrollbar.set)
        alias_list.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def refresh_aliases() -> None:
            alias_list.delete(0, "end")
            for alias in aliases:
                alias_list.insert("end", alias)

        def add_alias(_event=None):
            candidate = alias_entry.get().strip()
            existing = {self._name_key(alias) for alias in [name, *aliases]}
            if candidate and self._name_key(candidate) not in existing:
                aliases.append(candidate)
                refresh_aliases()
            alias_entry.delete(0, "end")
            alias_entry.focus_set()
            return "break"

        def delete_alias() -> None:
            selected = alias_list.curselection()
            if selected:
                del aliases[selected[0]]
                refresh_aliases()

        ttk.Button(add_row, text=tr("Add"), command=add_alias).pack(side="left", padx=(6, 0))
        ttk.Button(add_row, text=tr("Delete Selected"), command=delete_alias).pack(side="left", padx=(6, 0))
        alias_entry.bind("<Return>", add_alias)
        alias_list.bind("<Delete>", lambda _event: delete_alias())
        refresh_aliases()

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(10, 0))
        ttk.Button(controls, text=tr("Cancel"), command=popup.destroy).pack(side="right")

        def apply_aliases() -> None:
            self.members[name] = aliases
            popup.destroy()
            self._render_rows()

        ttk.Button(controls, text=tr("Apply"), command=apply_aliases).pack(side="right", padx=(0, 8))
        self.system_theme.theme_window(popup)
        alias_entry.focus_set()

    def _save(self) -> None:
        try:
            members = save_roster(self.roster_path, self.members)
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror(tr("Could not save members"), str(error), parent=self.dialog)
            return
        self.on_saved(len(members))
        self.dialog.destroy()


class ParserWindow:
    def __init__(self) -> None:
        enable_per_monitor_dpi()
        set_windows_app_id()
        self.root = TkinterDnD.Tk()
        configure_app_fonts(self.root)
        self.root.system_theme = SystemTheme(self.root)
        self.dpi_monitor = DpiMonitor(self.root)
        self.app_icon = tk.PhotoImage(file=str(ASSETS_DIR / "last-war-vs-scanner.png"))
        self.header_icon = tk.PhotoImage(file=str(ASSETS_DIR / "last-war-vs-scanner-64.png"))
        self.root.iconphoto(True, self.app_icon)
        self.root.title(tr("Last War VS Scanner"))
        set_scaled_window_size(self.root, 1100, 760, 760, 480)

        self.events: queue.Queue[tuple] = queue.Queue()
        self.rows: dict[str, list[dict]] = {slot: [] for slot in SLOTS}
        self.output_dirs: dict[str, Path | None] = {slot: None for slot in SLOTS}
        self.slot_versions = {slot: 0 for slot in SLOTS}
        self.pending: list[tuple[str, Path, int]] = []
        self.current_job: tuple[str, Path, int] | None = None
        self.current_cancel: threading.Event | None = None
        self.drop_areas: dict[str, DropCard] = {}
        self.tables: dict[str, ttk.Treeview] = {}
        self.roster_path = ROOT / "data" / "member_roster.json"
        self.history_dir = ROOT / "data" / "weeks"
        self.selected_week = iso_week()
        self.source_names: dict[str, str] = {slot: "" for slot in SLOTS}
        self.push_days: dict[str, bool] = {slot: True for slot in DAILY_SLOTS}
        self.support_popup: tk.Toplevel | None = None
        self.tutorial_popup: tk.Toplevel | None = None

        self._build_ui()
        self.root.system_theme.theme_window(self.root)
        self._load_selected_week()
        self.root.after(100, self._handle_events)
        if should_show_first_launch_tip(ROOT / "data"):
            self.root.after_idle(self._show_alliance_members_tip)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)

        header = ttk.Frame(frame)
        header.pack(fill="x")
        ttk.Label(
            header,
            text=tr("Last War VS Scanner"),
            image=self.header_icon,
            compound="left",
            font=(FONT_FAMILY, 18, "bold"),
        ).pack(side="left", padx=(0, 8))
        header_actions = ttk.Frame(header)
        header_actions.pack(side="right")
        week_area = ttk.Frame(header_actions)
        week_area.pack(side="left", padx=(0, 12))
        ttk.Label(week_area, text=tr("ISO week"), font=(FONT_FAMILY, 9, "bold")).pack(anchor="w")
        self.week_selector = ttk.Combobox(
            week_area,
            values=selectable_weeks(self.history_dir),
            state="readonly",
            width=11,
        )
        self.week_selector.set(self.selected_week)
        self.week_selector.pack(anchor="w")
        self.week_selector.bind("<<ComboboxSelected>>", self._change_week)
        self.alliance_members_button = ttk.Button(
            header_actions, text=tr("Alliance Members"), command=self._edit_members,
        )
        self.alliance_members_button.pack(
            side="left", anchor="s"
        )
        ttk.Label(
            frame,
            text=tr("Drop six daily ranking videos and one weekly ranking video. They process in queue on this PC."),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 12))

        drops = ttk.Frame(frame)
        drops.pack(fill="x")
        for index, slot in enumerate(SLOTS):
            drop_area = DropCard(
                drops,
                slot,
                on_open=lambda selected=slot: self._select_slot(selected),
                on_browse=lambda selected=slot: self._choose_video(selected),
                on_clear=lambda selected=slot: self._clear_slot(selected),
                on_push=(lambda selected=slot: self._toggle_push_day(selected))
                if slot in DAILY_SLOTS else None,
            )
            row, column = divmod(index, 4)
            drop_area.grid(row=row, column=column, sticky="nsew", padx=4, pady=4)
            for target in (drop_area, drop_area.title, drop_area.message):
                target.drop_target_register(DND_FILES)
                target.dnd_bind("<<Drop>>", lambda event, selected=slot: self._on_drop(event, selected))
            self.drop_areas[slot] = drop_area
        self.push_summary_card = ActionCard(
            drops,
            slot_label(PUSH_SUMMARY),
            tr("Open combined push ranking"),
            on_open=lambda: self._select_slot(PUSH_SUMMARY),
        )
        summary_index = len(SLOTS)
        summary_row, summary_column = divmod(summary_index, 4)
        self.push_summary_card.grid(
            row=summary_row, column=summary_column, sticky="nsew", padx=4, pady=4,
        )
        for column in range(4):
            drops.columnconfigure(column, weight=1)

        self.status = ttk.Label(frame, text=tr("Ready"), padding=(0, 10, 0, 4))
        self.status.pack(fill="x")

        self.notebook = ttk.Notebook(frame, style="Tabless.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        for slot in VIEW_SLOTS:
            table_frame = ttk.Frame(self.notebook)
            self.notebook.add(table_frame, text=slot_label(slot))
            self.tables[slot] = self._build_table(table_frame, editable=slot != PUSH_SUMMARY)
        self.notebook.bind("<<NotebookTabChanged>>", self._sync_selected_card)
        self._sync_selected_card()
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text=tr("Copy Selected Table"), command=self._copy_selected_table).pack(
            side="left"
        )
        ttk.Button(buttons, text=tr("Copy All Week Tables"), command=self._copy_all_week_tables).pack(
            side="left", padx=(8, 0)
        )
        support_button = SupportButton(buttons, self._open_support_qr)
        support_button.pack(side="right", padx=(12, 0))

    def _open_support_qr(self, _event: tk.Event | None = None) -> None:
        if self.support_popup is not None and self.support_popup.winfo_exists():
            self.support_popup.lift()
            self.support_popup.focus_set()
            return

        popup = tk.Toplevel(self.root)
        self.support_popup = popup
        popup.title(tr("Buy Crocco a coffee"))
        popup.transient(self.root)
        popup.resizable(False, False)
        popup.qr_image = resampled_photo(ASSETS_DIR / "crocco-support-qr.png", (375, 375), popup)
        ttk.Label(popup, image=popup.qr_image).pack(padx=12, pady=(12, 6))
        support_link = ttk.Label(popup, text=SUPPORT_URL, cursor="hand2", style="Link.TLabel")
        support_link.pack(padx=12, pady=(0, 12))
        support_link.bind("<Button-1>", lambda _event: webbrowser.open_new_tab(SUPPORT_URL))
        support_link.bind("<Return>", lambda _event: webbrowser.open_new_tab(SUPPORT_URL))
        support_link.configure(takefocus=True)

        def close_popup(_event: tk.Event | None = None) -> None:
            popup.destroy()
            self.support_popup = None

        popup.protocol("WM_DELETE_WINDOW", close_popup)
        popup.bind("<Escape>", close_popup)
        self.root.system_theme.theme_window(popup)
        popup.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - popup.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - popup.winfo_height()) // 2
        popup.geometry(f"+{max(0, x)}+{max(0, y)}")
        popup.focus_set()

    def _build_table(self, table_frame: ttk.Frame, editable: bool = True) -> ttk.Treeview:
        table = ttk.Treeview(table_frame, columns=DISPLAY_COLUMNS, show="headings", selectmode="extended")
        widths = (60, 120, 80, 100, 100)
        for column, heading, width in zip(DISPLAY_COLUMNS, HEADINGS, widths, strict=True):
            table.heading(column, text=heading)
            table.column(column, width=width, minwidth=50, anchor="w", stretch=column == "issues")
        table.column("rank", anchor="e")
        table.column("points", anchor="e")
        table.column("confidence", anchor="e")
        table.tag_configure("non_member", background="#ffd6d6")
        table.tag_configure("missing_member", background="#fff2cc")

        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=table.xview)
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        table.bind("<Control-c>", lambda _event: self._copy_selected())
        if editable:
            table.bind("<Button-1>", self._show_name_menu)
            table.bind("<Double-Button-1>", self._edit_table_cell)
        return table

    def _change_week(self, _event=None) -> None:
        requested = self.week_selector.get()
        if self.current_job is not None or self.pending:
            messagebox.showinfo(tr("Processing in progress"), tr("Wait for queued recordings before changing weeks."))
            self.week_selector.set(self.selected_week)
            return
        self.selected_week = requested
        self._load_selected_week()

    def _load_selected_week(self) -> None:
        try:
            state = load_week(self.history_dir, self.selected_week)
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror(tr("Could not open week"), str(error))
            state = {"slots": {}}
        stored_slots = state.get("slots", {})
        for slot in DAILY_SLOTS:
            self.push_days[slot] = bool(stored_slots.get(slot, {}).get("push_day", True))
            self.drop_areas[slot].set_push_day(self.push_days[slot])
        for slot in SLOTS:
            saved = stored_slots.get(slot, {})
            self.rows[slot] = saved.get("rows", [])
            self.source_names[slot] = saved.get("source_name", "")
            output_value = saved.get("output_dir")
            self.output_dirs[slot] = ROOT / output_value if output_value else None
            self._render_slot(slot)
        self._render_push_summary()
        self.status.configure(text=tr("{week} loaded.", week=self.selected_week))

    def _render_slot(self, slot: str) -> None:
        table = self.tables[slot]
        for item in table.get_children():
            table.delete(item)
        for index, row in enumerate(self.rows[slot]):
            values = (
                row.get("rank") if row.get("rank") is not None else "",
                row.get("name", ""),
                format_points(row.get("points")),
                f'{float(row.get("confidence", 0)):.3f}',
                row.get("issues", ""),
            )
            issues = row.get("issues", "")
            tags = ("non_member",) if "not in alliance member list" in issues else ()
            if "added with zero points" in issues:
                tags = ("missing_member",)
            table.insert("", "end", iid=str(index), values=values, tags=tags)
        if self.rows[slot]:
            self._fit_result_columns(table)
            filename = self.source_names[slot] or tr("saved recording")
            self.drop_areas[slot].show_state(tr("Ready - hover for file"), filename)
        else:
            self.drop_areas[slot].show_state(tr("Drop MP4 here"), clear=False)
        if slot in DAILY_SLOTS:
            self._render_push_summary()

    def _render_push_summary(self) -> None:
        table = self.tables[PUSH_SUMMARY]
        for item in table.get_children():
            table.delete(item)
        rows = aggregate_push_rows(self.rows, self.push_days)
        for index, row in enumerate(rows):
            table.insert(
                "", "end", iid=str(index),
                values=(row["rank"], row["name"], format_points(row["points"]), "", ""),
            )
        if rows:
            self._fit_result_columns(table)

    def _toggle_push_day(self, slot: str) -> None:
        self.push_days[slot] = self.drop_areas[slot].push_var.get()
        self._render_push_summary()
        self._save_selected_week()
        selected = sum(self.push_days.values())
        self.status.configure(text=tr("{count} push day(s) selected for {week}.", count=selected, week=self.selected_week))

    def _save_selected_week(self) -> None:
        slots = {}
        for slot in SLOTS:
            is_push_day = self.push_days.get(slot, False)
            if slot not in DAILY_SLOTS and not self.rows[slot]:
                continue
            output_dir = self.output_dirs[slot]
            try:
                output_value = str(output_dir.relative_to(ROOT)) if output_dir else ""
            except ValueError:
                output_value = str(output_dir) if output_dir else ""
            slots[slot] = {
                "source_name": self.source_names[slot],
                "output_dir": output_value,
                "rows": self.rows[slot],
            }
            if slot in DAILY_SLOTS:
                slots[slot]["push_day"] = is_push_day
        save_week(self.history_dir, self.selected_week, slots)
        weeks = selectable_weeks(self.history_dir)
        self.week_selector.configure(values=weeks)

    def _edit_table_cell(self, event) -> None:
        table = event.widget
        item = table.identify_row(event.y)
        column_id = table.identify_column(event.x)
        editable = {"#1": "rank", "#3": "points"}
        field = editable.get(column_id)
        if not item or not field:
            return
        slot = next(name for name, candidate in self.tables.items() if candidate is table)
        row = self.rows[slot][int(item)]
        initial = "" if row.get(field) is None else str(row[field])
        localized_field = tr(field.title())
        value = simpledialog.askstring(tr("Edit result"), tr("{field}:", field=localized_field), initialvalue=initial, parent=self.root)
        if value is None:
            return
        value = value.strip()
        if field in {"rank", "points"}:
            try:
                row[field] = int(value) if value else None
            except ValueError:
                messagebox.showerror(tr("Invalid value"), tr("{field} must be a whole number.", field=localized_field))
                return
        elif not value:
            messagebox.showerror(tr("Invalid value"), tr("Name cannot be empty."))
            return
        else:
            row[field] = value
        self._render_slot(slot)
        self._save_selected_week()
        if self.output_dirs[slot]:
            write_row_exports(self.rows[slot], self.output_dirs[slot])
        self.status.configure(text=tr("Saved edit in {week}, {slot}.", week=self.selected_week, slot=slot_label(slot)))

    def _show_name_menu(self, event) -> str | None:
        table = event.widget
        item = table.identify_row(event.y)
        if not item or table.identify_column(event.x) != "#2":
            return None
        slot = next(name for name, candidate in self.tables.items() if candidate is table)
        row_index = int(item)
        table.selection_set(item)

        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label=tr("Edit"), command=lambda: self._edit_result_name(slot, row_index))
        row = self.rows[slot][row_index]
        if "not in alliance member list" in str(row.get("issues", "")):
            menu.add_command(
                label=tr("Add to alliance"),
                command=lambda: self._add_result_to_alliance(slot, row_index),
            )
            assign_menu = tk.Menu(menu, tearoff=False)
            roster = load_roster(self.roster_path)
            available = available_roster_members(self.rows[slot], roster)
            if available:
                for member in available:
                    assign_menu.add_command(
                        label=member,
                        command=lambda selected=member: self._assign_result_name(slot, row_index, selected),
                    )
            else:
                assign_menu.add_command(label=tr("No unassigned members"), state="disabled")
            menu.add_cascade(label=tr("Assign from alliance"), menu=assign_menu)
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _edit_result_name(self, slot: str, row_index: int) -> None:
        row = self.rows[slot][row_index]
        value = simpledialog.askstring(
            tr("Edit name"), tr("{field}:", field=tr("Name")), initialvalue=str(row.get("name", "")), parent=self.root
        )
        if value is None:
            return
        value = value.strip()
        if not value:
            messagebox.showerror(tr("Invalid value"), tr("Name cannot be empty."))
            return
        displayed_name = edit_result_name(self.rows[slot], row_index, value, load_roster(self.roster_path))
        self._save_and_refresh_slots([slot])
        self.status.configure(text=tr('Saved name "{name}" for {week}, {slot}.', name=displayed_name, week=self.selected_week, slot=slot_label(slot)))

    def _assign_result_name(self, slot: str, row_index: int, member: str) -> None:
        alias = str(self.rows[slot][row_index].get("name", "")).strip()
        roster = load_roster(self.roster_path)
        aliases = roster.get(member)
        if aliases is None:
            messagebox.showerror(tr("Member unavailable"), tr('Alliance member "{name}" no longer exists.', name=member))
            return
        if alias and alias.casefold() != member.casefold() and all(alias.casefold() != value.casefold() for value in aliases):
            aliases.append(alias)
        save_roster(self.roster_path, roster)

        changed_slots = []
        for candidate_slot in SLOTS:
            if apply_roster_alias(self.rows[candidate_slot], alias, member):
                changed_slots.append(candidate_slot)
        self._save_and_refresh_slots(changed_slots)
        self.status.configure(
            text=tr('Assigned "{alias}" to {member} and refreshed {count} result set(s).', alias=alias, member=member, count=len(changed_slots))
        )

    def _add_result_to_alliance(self, slot: str, row_index: int) -> None:
        name = str(self.rows[slot][row_index].get("name", "")).strip()
        if not name:
            return
        roster = load_roster(self.roster_path)
        roster.setdefault(name, [])
        save_roster(self.roster_path, roster)

        changed_slots = []
        for candidate_slot in SLOTS:
            if apply_roster_alias(self.rows[candidate_slot], name, name):
                changed_slots.append(candidate_slot)
        self._save_and_refresh_slots(changed_slots)
        self.status.configure(
            text=tr('Added "{name}" to the alliance and refreshed {count} result set(s).', name=name, count=len(changed_slots))
        )

    def _save_and_refresh_slots(self, slots: list[str]) -> None:
        for slot in slots:
            self._render_slot(slot)
            if self.output_dirs[slot]:
                write_row_exports(self.rows[slot], self.output_dirs[slot])
        self._save_selected_week()

    def _fit_result_columns(self, table: ttk.Treeview) -> None:
        font = tkfont.nametofont("TkDefaultFont")
        for column, heading in zip(DISPLAY_COLUMNS[:-1], HEADINGS[:-1], strict=True):
            values = (str(table.set(item, column)) for item in table.get_children())
            width = max((font.measure(value) for value in values), default=0)
            table.column(column, width=max(50, font.measure(heading) + 20, width + 20))

    def _choose_video(self, slot: str) -> None:
        path = filedialog.askopenfilename(title=tr("Choose a recording"), filetypes=[(tr("MP4 video"), "*.mp4")])
        if path:
            self._enqueue(slot, Path(path))

    def _select_slot(self, slot: str) -> None:
        self.notebook.select(VIEW_SLOTS.index(slot))
        self._set_selected_card(slot)

    def _sync_selected_card(self, _event=None) -> None:
        selected_index = self.notebook.index(self.notebook.select())
        self._set_selected_card(VIEW_SLOTS[selected_index])

    def _set_selected_card(self, slot: str) -> None:
        for card_slot, card in self.drop_areas.items():
            card.set_selected(card_slot == slot)
        self.push_summary_card.set_selected(slot == PUSH_SUMMARY)

    def _clear_slot(self, slot: str) -> None:
        if any(job[0] == slot for job in self.pending):
            self._cancel_queued(slot)
            return
        if self.current_job is not None and self.current_job[0] == slot:
            if self.current_cancel is not None:
                self.current_cancel.set()
                self.drop_areas[slot].show_state(
                    tr("Cancelling..."), progress=0, browse=False
                )
                self.status.configure(text=tr("Cancelling {slot}...", slot=slot_label(slot)))
            return
        self.slot_versions[slot] += 1
        self.rows[slot] = []
        self.source_names[slot] = ""
        self.output_dirs[slot] = None
        self._render_slot(slot)
        self._save_selected_week()
        self.status.configure(text=tr("Cleared {slot}.", slot=slot_label(slot)))

    def _on_drop(self, event, slot: str) -> None:
        paths = self.root.tk.splitlist(event.data)
        if paths:
            self._enqueue(slot, Path(paths[0]))

    def _enqueue(self, slot: str, video_path: Path) -> None:
        if video_path.suffix.lower() != ".mp4" or not video_path.is_file():
            messagebox.showerror(tr("Unsupported file"), tr("Please drop an existing .mp4 video."))
            return

        self.slot_versions[slot] += 1
        version = self.slot_versions[slot]
        self.pending = [job for job in self.pending if job[0] != slot]
        self.pending.append((slot, video_path, version))
        self.rows[slot] = []
        self.source_names[slot] = ""
        self.output_dirs[slot] = None
        table = self.tables[slot]
        for item in table.get_children():
            table.delete(item)
        self.drop_areas[slot].show_state(tr("Queued..."), progress=0, browse=False)
        self.status.configure(text=tr("Queued {filename} for {slot}. {count} waiting.", filename=video_path.name, slot=slot_label(slot), count=len(self.pending)))
        self._start_next()

    def _cancel_queued(self, slot: str) -> None:
        remaining = [job for job in self.pending if job[0] != slot]
        if len(remaining) == len(self.pending):
            return

        self.pending = remaining
        self.slot_versions[slot] += 1
        self.rows[slot] = []
        self.source_names[slot] = ""
        self.output_dirs[slot] = None
        table = self.tables[slot]
        for item in table.get_children():
            table.delete(item)
        self.drop_areas[slot].show_state(tr("Drop MP4 here"), clear=False)
        self.status.configure(text=tr("Cancelled queued video for {slot}. {count} waiting.", slot=slot_label(slot), count=len(self.pending)))

    def _start_next(self) -> None:
        if self.current_job is not None or not self.pending:
            return
        slot, video_path, version = self.pending.pop(0)
        self.current_job = (slot, video_path, version)
        self.current_cancel = threading.Event()
        output_dir = ROOT / "output" / "weeks" / self.selected_week / slot.lower().replace(" ", "_")
        self.output_dirs[slot] = output_dir
        self.status.configure(text=tr("Opening {filename} for {slot}...", filename=video_path.name, slot=slot_label(slot)))
        self.drop_areas[slot].show_state(tr("Processing..."), progress=0, browse=False)

        threading.Thread(target=self._process, args=(slot, video_path, output_dir, version), daemon=True).start()

    def _process(self, slot: str, video_path: Path, output_dir: Path, version: int) -> None:
        cancel = self.current_cancel

        def update(current: int, total: int, message: str) -> None:
            if cancel is not None and cancel.is_set():
                raise ProcessingCancelled
            self.events.put(("progress", slot, version, current, total, message))

        try:
            results = process_video(video_path, output_dir, self.roster_path, update)
            if cancel is not None and cancel.is_set():
                self.events.put(("cancelled", slot, version))
            else:
                self.events.put(("complete", slot, version, video_path.name, results))
        except ProcessingCancelled:
            self.events.put(("cancelled", slot, version))
        except Exception as error:
            self.events.put(("error", slot, version, video_path.name, str(error)))

    def _handle_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, slot, version, current, total, message = event
                    if (
                        self.current_job is not None
                        and self.current_job[0] == slot
                        and self.current_job[2] == version
                    ):
                        self.drop_areas[slot].show_state(
                            message,
                            progress=(current / max(total, 1)) * 100,
                            browse=False,
                        )
                        self.status.configure(text=tr("{slot}: {message}", slot=slot_label(slot), message=message))
                elif event[0] == "complete":
                    self._show_results(*event[1:])
                elif event[0] == "error":
                    self._show_error(*event[1:])
                elif event[0] == "cancelled":
                    self._show_cancelled(*event[1:])
        except queue.Empty:
            pass
        self.root.after(100, self._handle_events)

    def _show_results(self, slot: str, version: int, filename: str, results) -> None:
        self.current_job = None
        self.current_cancel = None
        if version != self.slot_versions[slot]:
            self._start_next()
            return
        self.rows[slot] = [result.to_dict() for result in results]
        self.source_names[slot] = filename
        self._render_slot(slot)
        self._save_selected_week()
        self.status.configure(text=tr("{slot} complete: {count} result(s) from {filename}.", slot=slot_label(slot), count=len(self.rows[slot]), filename=filename))
        self._start_next()

    def _show_error(self, slot: str, version: int, filename: str, error: str) -> None:
        self.current_job = None
        self.current_cancel = None
        if version == self.slot_versions[slot]:
            self.status.configure(text=tr("{slot} processing failed", slot=slot_label(slot)))
            self.drop_areas[slot].show_state(tr("Failed - hover for file"), filename)
            messagebox.showerror(tr("Could not process {slot}", slot=slot_label(slot)), error)
        self._start_next()

    def _show_cancelled(self, slot: str, version: int) -> None:
        self.current_job = None
        self.current_cancel = None
        if version == self.slot_versions[slot]:
            self.rows[slot] = []
            self.source_names[slot] = ""
            self.output_dirs[slot] = None
            self._render_slot(slot)
            self.status.configure(text=tr("Cancelled {slot}.", slot=slot_label(slot)))
        self._start_next()

    def _active_slot(self) -> str:
        return VIEW_SLOTS[self.notebook.index(self.notebook.select())]

    def _active_table(self) -> ttk.Treeview:
        return self.tables[self._active_slot()]

    def _copy_selected(self) -> None:
        selected = self._active_table().selection()
        if not selected:
            return
        self._copy_items(selected)

    def _copy_selected_table(self) -> None:
        slot = self._active_slot()
        table = self.tables[slot]
        self._copy_text(self._table_text(table))
        self.status.configure(text=tr("Copied the {slot} table to the clipboard.", slot=slot_label(slot)))

    def _copy_all_week_tables(self) -> None:
        self._copy_text(self._week_tables_text(self.tables))
        self.status.configure(text=tr("Copied all {count} tables for {week} to the clipboard.", count=len(SLOTS), week=self.selected_week))

    @staticmethod
    def _table_text(table: ttk.Treeview, items=None) -> str:
        selected_items = table.get_children() if items is None else items
        lines = ["\t".join(COPY_HEADINGS)]
        lines.extend(
            "\t".join(str(value) for value in table.item(item, "values")[:COPY_COLUMN_COUNT])
            for item in selected_items
        )
        return "\n".join(lines)

    @staticmethod
    def _week_tables_text(tables: dict[str, ttk.Treeview]) -> str:
        table_rows = []
        for slot in SLOTS:
            table = tables[slot]
            rows = [
                tuple(str(value) for value in table.item(item, "values")[:COPY_COLUMN_COUNT])
                for item in table.get_children()
            ]
            table_rows.append(rows)

        def join_day_blocks(blocks) -> str:
            return "\t\t".join("\t".join(block) for block in blocks)

        lines = [join_day_blocks((slot_label(slot), "", "") for slot in SLOTS)]
        lines.append(join_day_blocks(COPY_HEADINGS for _slot in SLOTS))
        for index in range(max((len(rows) for rows in table_rows), default=0)):
            lines.append(
                join_day_blocks(
                    rows[index] if index < len(rows) else ("", "", "")
                    for rows in table_rows
                )
            )
        return "\n".join(lines)

    def _copy_text(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _copy_items(self, items) -> None:
        table = self._active_table()
        self._copy_text(self._table_text(table, items))
        self.status.configure(text=tr("Copied {count} row(s) to the clipboard.", count=len(items)))

    def _edit_members(self) -> None:
        self._dismiss_alliance_members_tip()
        MemberEditor(
            self.root,
            self.roster_path,
            lambda count: self.status.configure(text=tr("Saved {count} alliance member(s).", count=count)),
        )

    def _show_alliance_members_tip(self) -> None:
        if self.tutorial_popup is not None or not self.root.winfo_exists():
            return
        self.root.update_idletasks()
        popup = tk.Toplevel(self.root)
        self.tutorial_popup = popup
        popup.overrideredirect(True)
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding=12, relief="solid", borderwidth=1)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=tr("Start here"), font=(FONT_FAMILY, 11, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text=tr("Add your alliance members first so scanned names can be matched correctly."),
            wraplength=290,
            justify="left",
        ).pack(anchor="w", pady=(4, 10))
        ttk.Button(frame, text=tr("Got it"), command=self._dismiss_alliance_members_tip).pack(anchor="e")

        popup.update_idletasks()
        button = self.alliance_members_button
        x = button.winfo_rootx() + button.winfo_width() - popup.winfo_reqwidth()
        y = button.winfo_rooty() + button.winfo_height() + 6
        popup.geometry(f"+{max(0, x)}+{max(0, y)}")
        popup.bind("<Escape>", lambda _event: self._dismiss_alliance_members_tip())
        self.root.system_theme.theme_window(popup)
        popup.lift(self.root)
        popup.attributes("-topmost", True)
        popup.after(250, lambda: popup.attributes("-topmost", False) if popup.winfo_exists() else None)
        button.focus_set()

    def _dismiss_alliance_members_tip(self) -> None:
        if self.tutorial_popup is not None:
            self.tutorial_popup.destroy()
            self.tutorial_popup = None
            mark_first_launch_tip_seen(ROOT / "data")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    ParserWindow().run()
