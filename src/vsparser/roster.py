from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from .models import MemberResult


def _skeleton(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def load_roster(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(name): [str(alias) for alias in aliases] for name, aliases in data.items()}


def parse_member_list(value: str) -> list[str]:
    members = []
    seen = set()
    for line in value.splitlines():
        name = line.strip()
        key = _skeleton(name)
        if name and key and key not in seen:
            members.append(name)
            seen.add(key)
    return members


def save_member_list(path: Path, value: str) -> list[str]:
    existing = load_roster(path)
    members = parse_member_list(value)
    roster = {name: existing.get(name, []) for name in members}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(roster, ensure_ascii=False, indent=2), encoding="utf-8")
    return members


def match_roster_name(value: str, roster: dict[str, list[str]]) -> tuple[str, float] | None:
    source = _skeleton(value)
    if len(source) < 3:
        return None
    scores = []
    for canonical, aliases in roster.items():
        candidates = [canonical, *aliases]
        score = max(SequenceMatcher(None, source, _skeleton(candidate)).ratio() for candidate in candidates)
        scores.append((score, canonical))
    scores.sort(reverse=True)
    if not scores:
        return None
    best_score, best_name = scores[0]
    second_score = scores[1][0] if len(scores) > 1 else 0.0
    if best_score >= 0.90 and best_score - second_score >= 0.08:
        return best_name, best_score
    return None


def find_most_similar_roster_name(
    value: str,
    roster: dict[str, list[str]],
    minimum_score: float = 0.55,
) -> tuple[str, float] | None:
    source = _skeleton(value)
    if len(source) < 3:
        return None

    best = None
    for canonical, aliases in roster.items():
        score = max(
            SequenceMatcher(None, source, _skeleton(candidate)).ratio()
            for candidate in [canonical, *aliases]
            if _skeleton(candidate)
        )
        if best is None or score > best[1]:
            best = canonical, score
    return best if best and best[1] >= minimum_score else None


def reconcile_results(results: list[MemberResult], roster: dict[str, list[str]]) -> list[MemberResult]:
    if not roster:
        return results

    canonical_by_key = {_skeleton(name): name for name in roster}
    present = set()
    unresolved = []
    for result in results:
        original_name = result.name
        canonical = canonical_by_key.get(_skeleton(original_name))
        if canonical is None:
            unresolved.append(result)
            continue
        result.name = canonical
        present.add(canonical)
        if canonical != original_name:
            result.issues.append("name corrected from alliance member list (100%)")

    for result in unresolved:
        available = {name: aliases for name, aliases in roster.items() if name not in present}
        match = match_roster_name(result.name, available)
        if match is None:
            match = find_most_similar_roster_name(result.name, available)
        if match is None:
            result.issues.append("not in alliance member list")
            result.review = True
            continue
        canonical, match_score = match
        result.name = canonical
        present.add(canonical)
        result.issues.append(f"name corrected from alliance member list ({match_score:.0%})")

    for name in roster:
        if name in present:
            continue
        results.append(
            MemberResult(
                name=name,
                points=0,
                rank=None,
                raw_name="",
                raw_points="",
                raw_rank="",
                confidence=1.0,
                review=False,
                issues=["not present in VS list; added with zero points"],
                timestamps=[],
                source_frames=[],
                observation_count=0,
            )
        )
    return results


def remember_names(path: Path, rows: list[dict]) -> None:
    roster = load_roster(path)
    for row in rows:
        canonical = str(row.get("name", "")).strip()
        if not canonical:
            continue
        aliases = roster.setdefault(canonical, [])
        raw_values = re.split(r"\s+\|\s+", str(row.get("raw_name", "")))
        for alias in raw_values:
            alias = alias.strip()
            if alias and alias != canonical and alias not in aliases:
                aliases.append(alias)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(roster, ensure_ascii=False, indent=2), encoding="utf-8")
