from __future__ import annotations

import re
import unicodedata

from .models import OCRToken, Observation
from .multilingual import is_right_to_left


POINT_CANDIDATE = re.compile(r"(?<!\w)[\dOoIl|][\dOoIl|,. ]{4,}[\dOoIl|](?!\w)")
RANK_CANDIDATE = re.compile(r"^\s*[\dOoIl|]{1,3}\s*$")
TRANSLATION = str.maketrans({"O": "0", "o": "0", "I": "1", "L": "1", "l": "1", "|": "1"})


def normalize_points(raw: str) -> int | None:
    normalized = raw.translate(TRANSLATION)
    digits = re.sub(r"\D", "", normalized)
    if len(digits) < 4:
        return None
    return int(digits)


def normalize_rank(raw: str) -> int | None:
    normalized = re.sub(r"\D", "", raw.translate(TRANSLATION))
    if not normalized:
        return None
    value = int(normalized)
    return value if 1 <= value <= 999 else None


def normalize_name(raw: str) -> str:
    value = unicodedata.normalize("NFKC", raw).strip()
    return re.sub(r"\s+", " ", value)


def _looks_like_alliance(text: str) -> bool:
    lowered = text.lower()
    return "fellas" in lowered or "vips" in lowered or "[" in text or "]" in text


def parse_observations(
    tokens: list[OCRToken],
    bounds: tuple[int, int, int, int],
    width: int,
    height: int,
    timestamp: float,
    frame_index: int,
    source_frame: str,
) -> list[Observation]:
    left, top, right, bottom = bounds
    inside = [t for t in tokens if left <= t.center_x <= right and top <= t.center_y <= bottom]
    point_tokens = [
        t for t in inside
        if t.center_x > width * 0.60 and POINT_CANDIDATE.search(t.text) and normalize_points(t.text) is not None
    ]
    observations = []
    for point_token in point_tokens:
        row_y = point_token.center_y
        name_candidates = [
            t for t in inside
            if width * 0.25 <= t.center_x < width * 0.72
            and -height * 0.035 <= t.center_y - row_y <= height * 0.008
            and not _looks_like_alliance(t.text)
            and not POINT_CANDIDATE.fullmatch(t.text)
        ]
        if not name_candidates:
            continue
        rtl = sum(is_right_to_left(token.text) for token in name_candidates) > len(name_candidates) / 2
        name_candidates.sort(key=lambda token: token.left, reverse=rtl)
        raw_name = " ".join(token.text for token in name_candidates)
        name = normalize_name(raw_name)
        if not name or name.lower() in {"commander", "points", "ranking"}:
            continue

        rank_candidates = [
            t for t in inside
            if t.center_x < width * 0.23
            and abs(t.center_y - row_y) <= height * 0.027
            and RANK_CANDIDATE.match(t.text)
        ]
        rank_token = min(rank_candidates, key=lambda token: abs(token.center_y - row_y), default=None)
        rank = normalize_rank(rank_token.text) if rank_token else None
        confidences = [point_token.confidence, *(token.confidence for token in name_candidates)]
        if rank_token:
            confidences.append(rank_token.confidence)
        issues = []
        if rank is None:
            issues.append("rank missing or unreadable")
        if min(confidences) < 0.82:
            issues.append("low OCR confidence")
        observations.append(
            Observation(
                name=name,
                points=normalize_points(point_token.text),
                rank=rank,
                raw_name=raw_name,
                raw_points=point_token.text,
                raw_rank=rank_token.text if rank_token else "",
                confidence=min(confidences),
                timestamp_seconds=timestamp,
                frame_index=frame_index,
                source_frame=source_frame,
                issues=issues,
            )
        )
    return observations
