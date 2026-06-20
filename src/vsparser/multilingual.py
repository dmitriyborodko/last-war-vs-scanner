from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Iterable


class Script(StrEnum):
    ARABIC = "arabic"
    CHINESE = "chinese"
    CYRILLIC = "cyrillic"
    LATIN = "latin"
    NUMERIC = "numeric"
    COMMON = "common"


@dataclass(frozen=True)
class RecognitionCandidate:
    text: str
    confidence: float
    model: str


def scripts_in_text(value: str) -> set[Script]:
    scripts: set[Script] = set()
    for character in unicodedata.normalize("NFC", value):
        if character.isdigit():
            scripts.add(Script.NUMERIC)
            continue
        if not character.isalpha():
            continue
        code = ord(character)
        name = unicodedata.name(character, "")
        if 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F or 0x08A0 <= code <= 0x08FF:
            scripts.add(Script.ARABIC)
        elif "CJK" in name or 0x3400 <= code <= 0x9FFF:
            scripts.add(Script.CHINESE)
        elif "CYRILLIC" in name:
            scripts.add(Script.CYRILLIC)
        elif "LATIN" in name:
            scripts.add(Script.LATIN)
    return scripts or {Script.COMMON}


def dominant_script(value: str) -> Script:
    counts: dict[Script, int] = {}
    for character in value:
        script = next(iter(scripts_in_text(character)))
        if script != Script.COMMON:
            counts[script] = counts.get(script, 0) + 1
    return max(counts, key=counts.get) if counts else Script.COMMON


def is_right_to_left(value: str) -> bool:
    return any(unicodedata.bidirectional(character) in {"R", "AL", "AN"} for character in value)


def unicode_skeleton(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def roster_similarity(value: str, roster: dict[str, list[str]]) -> tuple[str | None, float]:
    source = unicode_skeleton(value)
    if not source:
        return None, 0.0
    best_name: str | None = None
    best_score = 0.0
    for canonical, aliases in roster.items():
        for roster_value in (canonical, *aliases):
            target = unicode_skeleton(roster_value)
            if not target:
                continue
            score = SequenceMatcher(None, source, target).ratio()
            if score > best_score:
                best_name, best_score = canonical, score
    return best_name, best_score


def select_name_candidate(
    candidates: Iterable[RecognitionCandidate],
    roster: dict[str, list[str]],
) -> RecognitionCandidate | None:
    candidates = [candidate for candidate in candidates if candidate.text.strip()]
    if not candidates:
        return None
    roster_scripts = set().union(*(scripts_in_text(name) for name in roster)) if roster else set()

    def score(candidate: RecognitionCandidate) -> float:
        text_scripts = scripts_in_text(candidate.text) - {Script.NUMERIC, Script.COMMON}
        script_bonus = 0.08 if not roster_scripts or text_scripts & roster_scripts else -0.08
        _, similarity = roster_similarity(candidate.text, roster)
        # Confidence remains primary unless a roster candidate is convincingly close.
        return candidate.confidence * 0.52 + similarity * 0.40 + script_bonus

    return max(candidates, key=score)
