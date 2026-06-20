from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .models import SelectedFrame, VideoInfo


def inspect_video(path: Path) -> VideoInfo:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"Could not open video: {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    if not fps or not frame_count or not width or not height:
        raise ValueError(f"Video metadata is incomplete: {path}")
    return VideoInfo(path, width, height, fps, frame_count, frame_count / fps)


def _sharpness(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _difference(first: np.ndarray, second: np.ndarray) -> float:
    first_small = cv2.resize(first, (64, 128), interpolation=cv2.INTER_AREA)
    second_small = cv2.resize(second, (64, 128), interpolation=cv2.INTER_AREA)
    return float(np.mean(cv2.absdiff(first_small, second_small)))


def select_frames(
    info: VideoInfo,
    sample_interval_seconds: float = 0.10,
    min_sharpness: float = 180.0,
    duplicate_difference: float = 1.4,
) -> list[SelectedFrame]:
    """Keep locally sharp, visually distinct frames at a bounded cadence."""
    capture = cv2.VideoCapture(str(info.path))
    candidates: list[SelectedFrame] = []
    step = max(1, round(info.fps * sample_interval_seconds))
    for index in range(0, info.frame_count, step):
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, image = capture.read()
        if not ok:
            continue
        sharpness = _sharpness(image)
        if sharpness < min_sharpness:
            continue
        candidates.append(SelectedFrame(index, index / info.fps, sharpness, image))
    capture.release()

    selected: list[SelectedFrame] = []
    for candidate in candidates:
        if selected and _difference(selected[-1].image, candidate.image) < duplicate_difference:
            if candidate.sharpness > selected[-1].sharpness:
                selected[-1] = candidate
            continue
        selected.append(candidate)
    return selected
