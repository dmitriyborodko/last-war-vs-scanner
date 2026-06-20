from datetime import date
from pathlib import Path

from vsparser.week_storage import iso_week, load_week, save_week, selectable_weeks


def test_iso_week_handles_year_boundary():
    assert iso_week(date(2021, 1, 1)) == "2020-W53"


def test_week_state_round_trip(tmp_path: Path):
    slots = {"Day 1": {"source_name": "day1.mp4", "rows": [{"name": "Alice", "points": 42}]}}
    save_week(tmp_path, "2026-W25", slots)
    assert load_week(tmp_path, "2026-W25") == {"week": "2026-W25", "slots": slots}
    assert load_week(tmp_path, "2026-W24") == {"week": "2026-W24", "slots": {}}


def test_selectable_weeks_includes_history_and_current(tmp_path: Path):
    (tmp_path / "2020-W01.json").write_text("{}", encoding="utf-8")
    weeks = selectable_weeks(tmp_path, count=2, today=date(2026, 6, 20))
    assert "2026-W25" in weeks
    assert "2020-W01" in weeks
