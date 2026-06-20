from __future__ import annotations

import numpy as np
from rapidocr_onnxruntime import RapidOCR

from .models import OCRToken


class RapidOCREngine:
    def __init__(self) -> None:
        self._engine = RapidOCR()

    def read(self, image: np.ndarray) -> list[OCRToken]:
        result, _ = self._engine(image)
        tokens = []
        for box, text, confidence in result or []:
            points = np.asarray(box, dtype=float)
            tokens.append(
                OCRToken(
                    text=text.strip(),
                    confidence=float(confidence),
                    left=float(points[:, 0].min()),
                    top=float(points[:, 1].min()),
                    right=float(points[:, 0].max()),
                    bottom=float(points[:, 1].max()),
                )
            )
        return tokens

