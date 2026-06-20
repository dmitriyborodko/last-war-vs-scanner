from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from .models import MemberResult
from .multilingual import unicode_skeleton


def _skeleton(value: str) -> str:
    return unicode_skeleton(value)


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


def save_roster(path: Path, roster: dict[str, list[str]]) -> list[str]:
    """Save canonical member names and their manually maintained aliases."""
    cleaned: dict[str, list[str]] = {}
    seen_names = set()
    for raw_name, raw_aliases in roster.items():
        name = str(raw_name).strip()
        key = _skeleton(name)
        if not name or not key or key in seen_names:
            continue
        seen_names.add(key)

        aliases = []
        seen_aliases = {key}
        for raw_alias in raw_aliases:
            alias = str(raw_alias).strip()
            alias_key = _skeleton(alias)
            if alias and alias_key and alias_key not in seen_aliases:
                aliases.append(alias)
                seen_aliases.add(alias_key)
        cleaned[name] = aliases

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    return list(cleaned)


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


def _row_issues(row: dict) -> list[str]:
    issues = row.get("issues", "")
    if isinstance(issues, list):
        return [str(issue).strip() for issue in issues if str(issue).strip()]
    return [issue.strip() for issue in str(issues).split(";") if issue.strip()]


def _is_missing_row(row: dict) -> bool:
    return "added with zero points" in str(row.get("issues", ""))


def _set_member_match(row: dict, canonical: str) -> None:
    row["name"] = canonical
    row["issues"] = "; ".join(
        issue for issue in _row_issues(row)
        if issue != "not in alliance member list" and "added with zero points" not in issue
    )


def available_roster_members(rows: list[dict], roster: dict[str, list[str]]) -> list[str]:
    """Return roster members that do not have a real result row for this slot."""
    canonical_by_key = {_skeleton(name): name for name in roster}
    present = {
        canonical_by_key[key]
        for row in rows
        if not _is_missing_row(row)
        for key in [_skeleton(str(row.get("name", "")))]
        if key in canonical_by_key
    }
    return [name for name in roster if name not in present]


def edit_result_name(
    rows: list[dict], row_index: int, new_name: str, roster: dict[str, list[str]]
) -> str:
    """Apply a day-only edit, matching it to an absent roster member when possible."""
    row = rows[row_index]
    other_rows = [candidate for index, candidate in enumerate(rows) if index != row_index]
    available = {name: roster[name] for name in available_roster_members(other_rows, roster)}
    match = match_roster_name(new_name, available)
    if match is None:
        match = find_most_similar_roster_name(new_name, available)
    canonical = match[0] if match else None

    if canonical:
        _set_member_match(row, canonical)
        rows[:] = [
            candidate for index, candidate in enumerate(rows)
            if index == row_index
            or not (_is_missing_row(candidate) and _skeleton(str(candidate.get("name", ""))) == _skeleton(canonical))
        ]
        return canonical

    row["name"] = new_name
    issues = [issue for issue in _row_issues(row) if "added with zero points" not in issue]
    if "not in alliance member list" not in issues:
        issues.append("not in alliance member list")
    row["issues"] = "; ".join(issues)
    return new_name


def apply_roster_alias(rows: list[dict], alias: str, canonical: str) -> bool:
    """Canonicalize an assigned spelling and remove its missing-member placeholder."""
    alias_key = _skeleton(alias)
    changed = False
    matched_real_row = False
    updated = []
    for row in rows:
        if not _is_missing_row(row) and _skeleton(str(row.get("name", ""))) == alias_key:
            _set_member_match(row, canonical)
            matched_real_row = True
            changed = True
        updated.append(row)
    if matched_real_row:
        filtered = [
            row for row in updated
            if not (_is_missing_row(row) and _skeleton(str(row.get("name", ""))) == _skeleton(canonical))
        ]
        changed = changed or len(filtered) != len(updated)
        rows[:] = filtered
    return changed


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
