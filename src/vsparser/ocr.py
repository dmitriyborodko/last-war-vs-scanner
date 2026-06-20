from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from rapidocr_onnxruntime import RapidOCR

from .models import OCRToken
from .multilingual import RecognitionCandidate, Script, scripts_in_text, select_name_candidate


MODEL_NAMES = {
    Script.LATIN: "PP-OCRv6_medium_rec",
    Script.CYRILLIC: "cyrillic_PP-OCRv5_mobile_rec",
    Script.ARABIC: "arabic_PP-OCRv5_mobile_rec",
    Script.CHINESE: "PP-OCRv6_medium_rec",
}


def default_model_dir() -> Path:
    configured = os.environ.get("VS_PARSER_MODEL_DIR")
    if configured:
        return Path(configured)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "models" / "paddleocr"
    return Path(__file__).resolve().parents[2] / "models" / "paddleocr"


def _read_paddle_result(result: Any) -> tuple[str, float] | None:
    if hasattr(result, "json"):
        result = result.json
    if isinstance(result, str):
        result = json.loads(result)
    if isinstance(result, dict):
        data = result.get("res", result)
        text = data.get("rec_text") or data.get("text")
        score = data.get("rec_score") or data.get("score")
        if text is not None and score is not None:
            return str(text).strip(), float(score)
    return None


class PaddleRecognizer:
    """Lazy wrapper around PaddleOCR's recognition-only pipeline."""

    def __init__(self, model_name: str, model_dir: Path) -> None:
        if not model_dir.is_dir() or not any(model_dir.iterdir()):
            raise FileNotFoundError(
                f"OCR model {model_name!r} is not installed at {model_dir}. "
                "Run run.ps1 -DownloadModels while online; video processing itself is offline."
            )
        try:
            from paddleocr import TextRecognition
        except ImportError as error:
            raise RuntimeError(
                "Multilingual OCR dependencies are missing. Run run.ps1 -Install first."
            ) from error
        self._model = TextRecognition(model_name=model_name, model_dir=str(model_dir), device="cpu")

    def read(self, crop: np.ndarray) -> RecognitionCandidate | None:
        results = self._model.predict(input=crop, batch_size=1)
        parsed = _read_paddle_result(next(iter(results), None))
        if not parsed:
            return None
        text, confidence = parsed
        return RecognitionCandidate(text, confidence, "paddle")


@lru_cache(maxsize=None)
def _recognizer(model_name: str, root: str) -> PaddleRecognizer:
    return PaddleRecognizer(model_name, Path(root) / model_name)


class MultilingualOCREngine:
    """Detect once with RapidOCR, then recognize name crops with routed models."""

    def __init__(self, model_dir: Path | None = None) -> None:
        self._detector = RapidOCR()
        self._model_dir = (model_dir or default_model_dir()).resolve()

    @staticmethod
    def _scripts_for_names(roster: dict[str, list[str]]) -> list[Script]:
        requested = {Script.LATIN, Script.CYRILLIC, Script.CHINESE, Script.ARABIC}
        requested.update(
            script for name in roster for script in scripts_in_text(name) if script in MODEL_NAMES
        )
        return sorted(requested, key=lambda script: script.value)

    @staticmethod
    def _crop(image: np.ndarray, token: OCRToken) -> np.ndarray:
        height, width = image.shape[:2]
        pad_x = max(2, round((token.right - token.left) * 0.04))
        pad_y = max(2, round((token.bottom - token.top) * 0.12))
        left, right = max(0, int(token.left) - pad_x), min(width, int(token.right) + pad_x)
        top, bottom = max(0, int(token.top) - pad_y), min(height, int(token.bottom) + pad_y)
        return image[top:bottom, left:right]

    def recognize_name_crop(
        self,
        crop: np.ndarray,
        roster: dict[str, list[str]],
        initial: RecognitionCandidate | None = None,
    ) -> RecognitionCandidate | None:
        candidates = [initial] if initial else []
        for script in self._scripts_for_names(roster):
            model_name = MODEL_NAMES[script]
            try:
                candidate = _recognizer(model_name, str(self._model_dir)).read(crop)
            except FileNotFoundError:
                continue
            if candidate:
                candidates.append(RecognitionCandidate(candidate.text, candidate.confidence, script.value))
        return select_name_candidate(candidates, roster)

    def read(self, image: np.ndarray, roster: dict[str, list[str]] | None = None) -> list[OCRToken]:
        roster = roster or {}
        result, _ = self._detector(image)
        tokens: list[OCRToken] = []
        for box, text, confidence in result or []:
            points = np.asarray(box, dtype=float)
            tokens.append(OCRToken(
                text=str(text).strip(), confidence=float(confidence),
                left=float(points[:, 0].min()), top=float(points[:, 1].min()),
                right=float(points[:, 0].max()), bottom=float(points[:, 1].max()),
            ))

        width = image.shape[1]
        for index, token in enumerate(tokens):
            if not width * 0.22 <= token.center_x < width * 0.74:
                continue
            crop = self._crop(image, token)
            initial = RecognitionCandidate(token.text, token.confidence, "rapidocr-ch")
            best = self.recognize_name_crop(crop, roster, initial)
            if best:
                tokens[index] = OCRToken(
                    text=best.text, confidence=best.confidence,
                    left=token.left, top=token.top, right=token.right, bottom=token.bottom,
                    recognition_model=best.model,
                )
        return tokens


RapidOCREngine = MultilingualOCREngine


@lru_cache(maxsize=1)
def get_ocr_engine() -> MultilingualOCREngine:
    return MultilingualOCREngine()
