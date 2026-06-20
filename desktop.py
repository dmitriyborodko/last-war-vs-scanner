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
SLOTS = tuple([f"Day {number}" for number in range(1, 7)] + ["Weekly Overall"])


class ParserWindow:
    def __init__(self) -> None:
        self.root = TkinterDnD.Tk()
        self.root.title("Last War VS Parser")
        self.root.geometry("1100x760")
        self.root.minsize(760, 480)

        self.events: queue.Queue[tuple] = queue.Queue()
        self.rows: dict[str, list[dict]] = {slot: [] for slot in SLOTS}
        self.output_dirs: dict[str, Path | None] = {slot: None for slot in SLOTS}
        self.slot_versions = {slot: 0 for slot in SLOTS}
        self.pending: list[tuple[str, Path, int]] = []
        self.current_job: tuple[str, Path, int] | None = None
        self.drop_areas: dict[str, ttk.Label] = {}
        self.tables: dict[str, ttk.Treeview] = {}
        self.roster_path = ROOT / "data" / "member_roster.json"

        self._build_ui()
        self.root.after(100, self._handle_events)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Last War VS Ranking Parser", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Drop six daily ranking videos and one weekly ranking video. They process in queue on this PC.",
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 12))

        drops = ttk.Frame(frame)
        drops.pack(fill="x")
        for index, slot in enumerate(SLOTS):
            drop_area = ttk.Label(
                drops,
                text=f"{slot}\nDrop MP4 or click to choose",
                anchor="center",
                justify="center",
                relief="ridge",
                padding=15,
                font=("Segoe UI", 10, "bold"),
            )
            row, column = divmod(index, 4)
            drop_area.grid(row=row, column=column, sticky="nsew", padx=4, pady=4)
            drop_area.bind("<Button-1>", lambda _event, selected=slot: self._choose_video(selected))
            drop_area.drop_target_register(DND_FILES)
            drop_area.dnd_bind("<<Drop>>", lambda event, selected=slot: self._on_drop(event, selected))
            self.drop_areas[slot] = drop_area
        for column in range(4):
            drops.columnconfigure(column, weight=1)

        self.status = ttk.Label(frame, text="Ready", padding=(0, 10, 0, 4))
        self.status.pack(fill="x")
        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 12))

        self.notebook = ttk.Notebook(frame)
        self.notebook.pack(fill="both", expand=True)
        for slot in SLOTS:
            table_frame = ttk.Frame(self.notebook)
            self.notebook.add(table_frame, text=slot)
            self.tables[slot] = self._build_table(table_frame)
        self.notebook.bind("<<NotebookTabChanged>>", lambda _event: self._update_output_button())

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Alliance Members", command=self._edit_members).pack(side="left")
        ttk.Button(buttons, text="Copy Selected", command=self._copy_selected).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Copy All", command=self._copy_all).pack(side="left", padx=(8, 0))
        self.open_button = ttk.Button(buttons, text="Open Output Folder", command=self._open_output, state="disabled")
        self.open_button.pack(side="right")

    def _build_table(self, table_frame: ttk.Frame) -> ttk.Treeview:
        table = ttk.Treeview(table_frame, columns=DISPLAY_COLUMNS, show="headings", selectmode="extended")
        widths = (60, 210, 120, 70, 90, 360)
        for column, heading, width in zip(DISPLAY_COLUMNS, HEADINGS, widths, strict=True):
            table.heading(column, text=heading)
            table.column(column, width=width, minwidth=50, anchor="w")
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
        return table

    def _choose_video(self, slot: str) -> None:
        path = filedialog.askopenfilename(title="Choose a recording", filetypes=[("MP4 video", "*.mp4")])
        if path:
            self._enqueue(slot, Path(path))

    def _on_drop(self, event, slot: str) -> None:
        paths = self.root.tk.splitlist(event.data)
        if paths:
            self._enqueue(slot, Path(paths[0]))

    def _enqueue(self, slot: str, video_path: Path) -> None:
        if video_path.suffix.lower() != ".mp4" or not video_path.is_file():
            messagebox.showerror("Unsupported file", "Please drop an existing .mp4 video.")
            return

        self.slot_versions[slot] += 1
        version = self.slot_versions[slot]
        self.pending = [job for job in self.pending if job[0] != slot]
        self.pending.append((slot, video_path, version))
        self.rows[slot] = []
        self.output_dirs[slot] = None
        table = self.tables[slot]
        for item in table.get_children():
            table.delete(item)
        self.drop_areas[slot].configure(text=f"{slot}\nQueued: {video_path.name}")
        self.status.configure(text=f"Queued {video_path.name} for {slot}. {len(self.pending)} waiting.")
        self._start_next()

    def _start_next(self) -> None:
        if self.current_job is not None or not self.pending:
            return
        slot, video_path, version = self.pending.pop(0)
        self.current_job = (slot, video_path, version)
        output_dir = ROOT / "output" / slot.lower().replace(" ", "_") / video_path.stem
        self.output_dirs[slot] = output_dir
        self.progress["value"] = 0
        self.status.configure(text=f"Opening {video_path.name} for {slot}...")
        self.drop_areas[slot].configure(text=f"{slot}\nProcessing: {video_path.name}")

        threading.Thread(target=self._process, args=(slot, video_path, output_dir, version), daemon=True).start()

    def _process(self, slot: str, video_path: Path, output_dir: Path, version: int) -> None:
        def update(current: int, total: int, message: str) -> None:
            self.events.put(("progress", slot, version, current, total, message))

        try:
            results = process_video(video_path, output_dir, self.roster_path, update)
            self.events.put(("complete", slot, version, video_path.name, results))
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
                        self.progress["value"] = (current / max(total, 1)) * 100
                        self.status.configure(text=f"{slot}: {message}")
                elif event[0] == "complete":
                    self._show_results(*event[1:])
                elif event[0] == "error":
                    self._show_error(*event[1:])
        except queue.Empty:
            pass
        self.root.after(100, self._handle_events)

    def _show_results(self, slot: str, version: int, filename: str, results) -> None:
        self.current_job = None
        self.progress["value"] = 100
        if version != self.slot_versions[slot]:
            self._start_next()
            return
        self.rows[slot] = [result.to_dict() for result in results]
        table = self.tables[slot]
        for row in self.rows[slot]:
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
            table.insert("", "end", values=values, tags=tags)
        self.status.configure(text=f"{slot} complete: {len(self.rows[slot])} result(s) from {filename}.")
        self.drop_areas[slot].configure(text=f"{slot}\nComplete: {filename}\nDrop again to reprocess")
        self._update_output_button()
        self._start_next()

    def _show_error(self, slot: str, version: int, filename: str, error: str) -> None:
        self.current_job = None
        self.progress["value"] = 0
        if version == self.slot_versions[slot]:
            self.status.configure(text=f"{slot} processing failed")
            self.drop_areas[slot].configure(text=f"{slot}\nFailed: {filename}\nDrop again to retry")
            messagebox.showerror(f"Could not process {slot}", error)
        self._start_next()

    def _active_slot(self) -> str:
        return SLOTS[self.notebook.index(self.notebook.select())]

    def _active_table(self) -> ttk.Treeview:
        return self.tables[self._active_slot()]

    def _update_output_button(self) -> None:
        output_dir = self.output_dirs[self._active_slot()]
        state = "normal" if output_dir and output_dir.exists() else "disabled"
        self.open_button.configure(state=state)

    def _copy_selected(self) -> None:
        selected = self._active_table().selection()
        if not selected:
            return
        self._copy_items(selected)

    def _copy_all(self) -> None:
        items = self._active_table().get_children()
        if items:
            self._copy_items(items)

    def _copy_items(self, items) -> None:
        table = self._active_table()
        lines = ["\t".join(HEADINGS)]
        lines.extend("\t".join(str(value) for value in table.item(item, "values")) for item in items)
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
        controls.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(controls, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(controls, text="Save Members", command=save).pack(side="right", padx=(0, 8))
        editor_frame.pack(fill="both", expand=True)
        editor.focus_set()

    def _open_output(self) -> None:
        output_dir = self.output_dirs[self._active_slot()]
        if output_dir and output_dir.exists():
            subprocess.Popen(["explorer", str(output_dir)])

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    ParserWindow().run()
