from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd

from .models import MemberResult


EXPORT_COLUMNS = [
    "rank", "name", "points", "review", "confidence", "issues",
    "raw_rank", "raw_name", "raw_points", "timestamps", "source_frames", "observation_count",
]


def results_frame(results: list[MemberResult]) -> pd.DataFrame:
    return pd.DataFrame([result.to_dict() for result in results], columns=EXPORT_COLUMNS)


def csv_bytes(data: pd.DataFrame) -> bytes:
    return data.to_csv(index=False).encode("utf-8-sig")


def xlsx_bytes(data: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        data.to_excel(writer, sheet_name="VS Rankings", index=False)
        sheet = writer.sheets["VS Rankings"]
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            width = min(60, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
            sheet.column_dimensions[column[0].column_letter].width = width
    return output.getvalue()


def write_exports(results: list[MemberResult], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = results_frame(results)
    csv_path = output_dir / "vs_rankings.csv"
    xlsx_path = output_dir / "vs_rankings.xlsx"
    csv_path.write_bytes(csv_bytes(data))
    xlsx_path.write_bytes(xlsx_bytes(data))
    return csv_path, xlsx_path

