from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable

import cv2

from .export import write_exports
from .layout import detect_list_bounds
from .localization import tr
from .merge import merge_observations
from .models import MemberResult
from .ocr import get_ocr_engine
from .parser import parse_observations
from .roster import load_roster, reconcile_results
from .video import inspect_video, select_frames


Progress = Callable[[int, int, str], None]


def process_video(
    video_path: Path,
    output_dir: Path,
    roster_path: Path | None = None,
    progress: Progress | None = None,
) -> list[MemberResult]:
    video_path = video_path.resolve()
    if video_path.suffix.lower() != ".mp4":
        raise ValueError("Input must be an .mp4 file")
    info = inspect_video(video_path)
    frames = select_frames(info)
    if not frames:
        raise ValueError("No sufficiently sharp frames were found")

    frame_dir = output_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    roster = load_roster(roster_path) if roster_path else {}
    ocr = get_ocr_engine()
    observations = []
    for number, frame in enumerate(frames, start=1):
        if progress:
            progress(number, len(frames), tr("OCR at {seconds:.2f}s", seconds=frame.timestamp_seconds))
        filename = f"frame_{frame.index:06d}_{frame.timestamp_seconds:08.3f}s.jpg"
        frame_path = frame_dir / filename
        cv2.imwrite(str(frame_path), frame.image)
        tokens = ocr.read(frame.image, roster)
        bounds = detect_list_bounds(frame.image, tokens)
        frame_observations = parse_observations(
                tokens, bounds, info.width, info.height,
                frame.timestamp_seconds, frame.index, str(frame_path.resolve()),
            )
        observations.extend(frame_observations)

    results = reconcile_results(merge_observations(observations), roster)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "observations.json").write_text(
        json.dumps([asdict(observation) for observation in observations], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "results.json").write_text(
        json.dumps([asdict(result) for result in results], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_exports(results, output_dir)
    return results
