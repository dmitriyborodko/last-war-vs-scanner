from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher

from .models import MemberResult, Observation


def _key(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def _similar(first: str, second: str) -> bool:
    left, right = _key(first), _key(second)
    return left == right or (min(len(left), len(right)) >= 5 and SequenceMatcher(None, left, right).ratio() >= 0.88)


def _mode(values: list):
    return Counter(values).most_common(1)[0][0] if values else None


def _weighted_point(group: list[Observation], chosen_rank: int | None) -> int | None:
    scores: Counter = Counter()
    eligible = [item for item in group if item.points is not None]
    rank_supported = [item for item in eligible if chosen_rank is not None and item.rank == chosen_rank]
    for item in rank_supported or eligible:
        scores[item.points] += item.confidence
    return scores.most_common(1)[0][0] if scores else None


def merge_observations(observations: list[Observation]) -> list[MemberResult]:
    groups: list[list[Observation]] = []
    for observation in sorted(observations, key=lambda item: item.timestamp_seconds):
        group = next(
            (
                items for items in groups
                if _similar(items[0].name, observation.name)
                or (
                    observation.points is not None
                    and any(item.points == observation.points for item in items)
                )
            ),
            None,
        )
        if group is None:
            groups.append([observation])
        else:
            group.append(observation)

    results = []
    for group in groups:
        names = [item.name for item in group]
        points = [item.points for item in group if item.points is not None]
        ranks = [item.rank for item in group if item.rank is not None]
        chosen_name = _mode(names)
        chosen_rank = _mode(ranks)
        chosen_points = _weighted_point(group, chosen_rank)
        evidence = max(
            group,
            key=lambda item: (
                item.name == chosen_name,
                item.points == chosen_points,
                item.rank == chosen_rank,
                item.confidence,
            ),
        )
        issues = sorted({issue for item in group for issue in item.issues})
        if len(set(points)) > 1:
            issues.append("conflicting point values")
        if len(set(ranks)) > 1:
            issues.append("conflicting ranks")
        if len(set(names)) > 1:
            issues.append("conflicting name spellings")
        if len(group) == 1:
            issues.append("seen in only one frame")
        confidence = sum(item.confidence for item in group) / len(group)
        results.append(
            MemberResult(
                name=chosen_name,
                points=chosen_points,
                rank=chosen_rank,
                raw_name=" | ".join(dict.fromkeys(item.raw_name for item in group if item.raw_name)),
                raw_points=" | ".join(dict.fromkeys(item.raw_points for item in group if item.raw_points)),
                raw_rank=" | ".join(dict.fromkeys(item.raw_rank for item in group if item.raw_rank)),
                confidence=round(confidence, 4),
                review=bool(issues) or confidence < 0.88,
                issues=issues,
                timestamps=sorted({round(item.timestamp_seconds, 3) for item in group}),
                source_frames=sorted({item.source_frame for item in group}),
                observation_count=len(group),
            )
        )
    results = sorted(results, key=lambda item: -(item.points or 0))
    _reconcile_rank_evidence(results)
    return sorted(results, key=lambda item: (item.rank is None, item.rank or 10_000, -(item.points or 0)))


def _reconcile_rank_evidence(results: list[MemberResult]) -> None:
    """Fill only ranks supported by adjacent, point-ordered observations."""
    anchored = [(index, result.rank) for index, result in enumerate(results) if result.rank is not None]
    offsets = Counter(rank - (index + 1) for index, rank in anchored)
    if len(anchored) >= 5 and offsets:
        offset, support = offsets.most_common(1)[0]
        if support / len(anchored) >= 0.75:
            for index, result in enumerate(results):
                expected = index + 1 + offset
                if result.rank == expected:
                    continue
                if result.rank is None:
                    result.issues = [issue for issue in result.issues if issue != "rank missing or unreadable"]
                    result.issues.append("rank inferred from list sequence")
                else:
                    result.issues.append(f"OCR rank {result.rank} resolved from list sequence")
                result.rank = expected
                result.review = True
            return

    for index, result in enumerate(results):
        previous = results[index - 1] if index > 0 else None
        following = results[index + 1] if index + 1 < len(results) else None
        expected = None
        if previous and following and previous.rank is not None and following.rank == previous.rank + 2:
            expected = previous.rank + 1
        elif index == 0 and following and following.rank == 2:
            expected = 1
        elif index == len(results) - 1 and previous and previous.rank is not None:
            expected = previous.rank + 1
        if expected is None:
            continue
        if result.rank is None:
            result.rank = expected
            result.issues = [issue for issue in result.issues if issue != "rank missing or unreadable"]
            result.issues.append("rank inferred from adjacent rows")
            result.review = True
        elif result.rank != expected and "conflicting ranks" in result.issues:
            result.rank = expected
            result.issues.append("rank resolved from adjacent rows")
            result.review = True
