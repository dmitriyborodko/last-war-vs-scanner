from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from tkinterdnd2 import DND_FILES, TkinterDnD


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from vsparser.pipeline import process_video  # noqa: E402
from vsparser.roster import load_roster, save_member_list  # noqa: E402


DISPLAY_COLUMNS = ("rank", "name", "points", "review", "confidence", "issues")
HEADINGS = ("Rank", "Name", "Points", "Review", "Confidence", "Issues")


class ParserWindow:
    def __init__(self) -> None:
        self.root = TkinterDnD.Tk()
        self.root.title("Last War VS Parser")
        self.root.geometry("1000x650")
        self.root.minsize(760, 480)

        self.events: queue.Queue[tuple] = queue.Queue()
        self.rows: list[dict] = []
        self.output_dir: Path | None = None
        self.roster_path = ROOT / "data" / "member_roster.json"
        self.busy = False

        self._build_ui()
        self.root.after(100, self._handle_events)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Last War VS Ranking Parser", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Drop an MP4 below. Processing stays on this PC.",
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 12))

        self.drop_area = ttk.Label(
            frame,
            text="Drop video here\n\nor click to choose an MP4",
            anchor="center",
            relief="ridge",
            padding=28,
            font=("Segoe UI", 12),
        )
        self.drop_area.pack(fill="x")
        self.drop_area.bind("<Button-1>", lambda _event: self._choose_video())
        self.drop_area.drop_target_register(DND_FILES)
        self.drop_area.dnd_bind("<<Drop>>", self._on_drop)

        self.status = ttk.Label(frame, text="Ready", padding=(0, 10, 0, 4))
        self.status.pack(fill="x")
        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 12))

        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=DISPLAY_COLUMNS, show="headings", selectmode="extended")
        widths = (60, 210, 120, 70, 90, 360)
        for column, heading, width in zip(DISPLAY_COLUMNS, HEADINGS, widths, strict=True):
            self.table.heading(column, text=heading)
            self.table.column(column, width=width, minwidth=50, anchor="w")
        self.table.column("rank", anchor="e")
        self.table.column("points", anchor="e")
        self.table.column("confidence", anchor="e")
        self.table.tag_configure("non_member", background="#ffd6d6")
        self.table.tag_configure("missing_member", background="#fff2cc")

        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table.bind("<Control-c>", lambda _event: self._copy_selected())

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Choose Video", command=self._choose_video).pack(side="left")
        ttk.Button(buttons, text="Alliance Members", command=self._edit_members).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Copy Selected", command=self._copy_selected).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Copy All", command=self._copy_all).pack(side="left", padx=(8, 0))
        self.open_button = ttk.Button(buttons, text="Open Output Folder", command=self._open_output, state="disabled")
        self.open_button.pack(side="right")

    def _choose_video(self) -> None:
        if self.busy:
            return
        path = filedialog.askopenfilename(title="Choose a recording", filetypes=[("MP4 video", "*.mp4")])
        if path:
            self._start(Path(path))

    def _on_drop(self, event) -> None:
        if self.busy:
            return
        paths = self.root.tk.splitlist(event.data)
        if paths:
            self._start(Path(paths[0]))

    def _start(self, video_path: Path) -> None:
        if video_path.suffix.lower() != ".mp4" or not video_path.is_file():
            messagebox.showerror("Unsupported file", "Please drop an existing .mp4 video.")
            return

        self.busy = True
        self.rows.clear()
        self.output_dir = ROOT / "output" / video_path.stem
        self.open_button.configure(state="disabled")
        self.progress["value"] = 0
        self.status.configure(text=f"Opening {video_path.name}...")
        self.drop_area.configure(text=f"Processing {video_path.name}\n\nPlease wait")
        for item in self.table.get_children():
            self.table.delete(item)

        threading.Thread(target=self._process, args=(video_path,), daemon=True).start()

    def _process(self, video_path: Path) -> None:
        def update(current: int, total: int, message: str) -> None:
            self.events.put(("progress", current, total, message))

        try:
            results = process_video(video_path, self.output_dir, self.roster_path, update)
            self.events.put(("complete", results))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _handle_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, current, total, message = event
                    self.progress["value"] = (current / max(total, 1)) * 100
                    self.status.configure(text=message)
                elif event[0] == "complete":
                    self._show_results(event[1])
                elif event[0] == "error":
                    self._show_error(event[1])
        except queue.Empty:
            pass
        self.root.after(100, self._handle_events)

    def _show_results(self, results) -> None:
        self.busy = False
        self.progress["value"] = 100
        self.rows = [result.to_dict() for result in results]
        for row in self.rows:
            values = (
                row["rank"] if row["rank"] is not None else "",
                row["name"],
                row["points"] if row["points"] is not None else "",
                "Yes" if row["review"] else "No",
                f'{row["confidence"]:.3f}',
                row["issues"],
            )
            tags = ()
            if "not in alliance member list" in row["issues"]:
                tags = ("non_member",)
            elif "added with zero points" in row["issues"]:
                tags = ("missing_member",)
            self.table.insert("", "end", values=values, tags=tags)
        self.status.configure(text=f"Complete: {len(self.rows)} result(s). Select rows and press Ctrl+C to copy.")
        self.drop_area.configure(text="Drop another video here\n\nor click to choose an MP4")
        self.open_button.configure(state="normal")

    def _show_error(self, error: str) -> None:
        self.busy = False
        self.progress["value"] = 0
        self.status.configure(text="Processing failed")
        self.drop_area.configure(text="Drop video here\n\nor click to choose an MP4")
        messagebox.showerror("Could not process video", error)

    def _copy_selected(self) -> None:
        selected = self.table.selection()
        if not selected:
            return
        self._copy_items(selected)

    def _copy_all(self) -> None:
        items = self.table.get_children()
        if items:
            self._copy_items(items)

    def _copy_items(self, items) -> None:
        lines = ["\t".join(HEADINGS)]
        lines.extend("\t".join(str(value) for value in self.table.item(item, "values")) for item in items)
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))
        self.status.configure(text=f"Copied {len(items)} row(s) to the clipboard.")

    def _edit_members(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Alliance Members")
        dialog.geometry("520x540")
        dialog.minsize(380, 320)
        dialog.transient(self.root)

        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Alliance members", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Paste one name per line from a spreadsheet. Edit the lines to add, rename, or remove members.",
            wraplength=470,
            foreground="#555555",
        ).pack(anchor="w", pady=(4, 10))

        editor_frame = ttk.Frame(frame)
        editor_frame.pack(fill="both", expand=True)
        editor = tk.Text(editor_frame, wrap="none", undo=True, font=("Segoe UI", 10))
        scrollbar = ttk.Scrollbar(editor_frame, orient="vertical", command=editor.yview)
        editor.configure(yscrollcommand=scrollbar.set)
        editor.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        try:
            editor.insert("1.0", "\n".join(load_roster(self.roster_path)))
        except (OSError, ValueError, TypeError) as error:
            dialog.destroy()
            messagebox.showerror("Could not open members", str(error))
            return

        def save() -> None:
            try:
                members = save_member_list(self.roster_path, editor.get("1.0", "end-1c"))
            except (OSError, ValueError, TypeError) as error:
                messagebox.showerror("Could not save members", str(error), parent=dialog)
                return
            self.status.configure(text=f"Saved {len(members)} alliance member(s).")
            dialog.destroy()

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(12, 0))
        ttk.Button(controls, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(controls, text="Save Members", command=save).pack(side="right", padx=(0, 8))
        editor.focus_set()

    def _open_output(self) -> None:
        if self.output_dir and self.output_dir.exists():
            subprocess.Popen(["explorer", str(self.output_dir)])

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    ParserWindow().run()
