from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from vsparser.multilingual import roster_similarity, unicode_skeleton
from vsparser.ocr import get_ocr_engine


def exact(actual: str, expected: str) -> bool:
    return unicode_skeleton(actual) == unicode_skeleton(expected)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark multilingual name OCR on labeled crops")
    parser.add_argument("manifest", type=Path, help="JSON rows: image, expected, optional roster")
    args = parser.parse_args()
    rows = json.loads(args.manifest.read_text(encoding="utf-8"))
    engine = get_ocr_engine()
    raw_correct = corrected_correct = 0
    report = []
    for row in rows:
        image_path = (args.manifest.parent / row["image"]).resolve()
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"Could not read {image_path}")
        roster = {name: [] for name in row.get("roster", [row["expected"]])}
        box = row.get("box")
        if box:
            left, top, right, bottom = box
            image = image[top:bottom, left:right]
        raw_candidate = engine.recognize_name_crop(image, {})
        raw = raw_candidate.text if raw_candidate else ""
        corrected, score = roster_similarity(raw, roster)
        corrected = corrected or raw
        raw_correct += exact(raw, row["expected"])
        corrected_correct += exact(corrected, row["expected"])
        report.append({
            "image": row["image"], "expected": row["expected"], "raw": raw,
            "roster_corrected": corrected, "roster_score": round(score, 4),
        })
    total = len(rows)
    summary = {
        "samples": total,
        "raw_name_accuracy": raw_correct / total if total else 0.0,
        "roster_corrected_name_accuracy": corrected_correct / total if total else 0.0,
        "results": report,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
