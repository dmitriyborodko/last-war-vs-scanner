from __future__ import annotations

import cv2
import numpy as np

from .models import OCRToken


def detect_list_bounds(image: np.ndarray, tokens: list[OCRToken]) -> tuple[int, int, int, int]:
    """Find the list using OCR headers, with resolution-relative visual fallbacks."""
    height, width = image.shape[:2]
    headers = [token for token in tokens if token.text.lower() in {"ranking", "commander", "points"}]
    lower_headers = [token for token in headers if token.center_y > height * 0.12]
    top = int(max((token.bottom for token in lower_headers), default=height * 0.23))

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    green = (hsv[:, :, 0] > 35) & (hsv[:, :, 0] < 95) & (hsv[:, :, 1] > 70)
    row_scores = green[:, int(width * 0.02) : int(width * 0.98)].mean(axis=1)
    green_rows = np.flatnonzero(row_scores > 0.35)
    bottom = int(green_rows[0]) if len(green_rows) else int(height * 0.80)
    if bottom <= top + height * 0.08:
        bottom = int(height * 0.80)
    return int(width * 0.02), top, int(width * 0.98), bottom

