from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


def iso_week(value: date | None = None) -> str:
    year, week, _ = (value or date.today()).isocalendar()
    return f"{year}-W{week:02d}"


def selectable_weeks(storage_dir: Path, count: int = 104, today: date | None = None) -> list[str]:
    current = today or date.today()
    weeks = {iso_week(current - timedelta(weeks=offset)) for offset in range(count)}
    if storage_dir.exists():
        weeks.update(path.stem for path in storage_dir.glob("????-W??.json"))
    return sorted(weeks, reverse=True)


def load_week(storage_dir: Path, week: str) -> dict:
    path = storage_dir / f"{week}.json"
    if not path.exists():
        return {"week": week, "slots": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("slots"), dict):
        raise ValueError(f"Invalid weekly history file: {path}")
    return data


def save_week(storage_dir: Path, week: str, slots: dict) -> Path:
    storage_dir.mkdir(parents=True, exist_ok=True)
    path = storage_dir / f"{week}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"week": week, "slots": slots}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path
