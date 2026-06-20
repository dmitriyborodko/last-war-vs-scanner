from vsparser.merge import merge_observations
from vsparser.models import Observation
from vsparser.parser import normalize_points, normalize_rank


def test_normalize_points_preserves_numeric_meaning():
    assert normalize_points("42,089,581") == 42_089_581
    assert normalize_points("8.34l.457") == 8_341_457
    assert normalize_points("score") is None


def test_normalize_rank_handles_common_ocr_substitutions():
    assert normalize_rank("6L") == 61
    assert normalize_rank("l9") == 19
    assert normalize_rank("") is None


def test_merge_flags_conflicting_values():
    common = dict(
        name="Alexej B", rank=14, raw_name="Alexej B", raw_rank="14",
        timestamp_seconds=1.0, frame_index=30, source_frame="frame.jpg", issues=[],
    )
    first = Observation(points=42_089_581, raw_points="42,089,581", confidence=0.98, **common)
    second = Observation(points=42_089_58, raw_points="42,089,58", confidence=0.90, **common)
    result = merge_observations([first, second])[0]
    assert result.review is True
    assert "conflicting point values" in result.issues


def test_merge_uses_identical_points_to_join_ocr_name_variants():
    common = dict(
        points=19_883_322, rank=35, raw_rank="35", raw_points="19,883,322",
        timestamp_seconds=1.0, frame_index=30, source_frame="frame.jpg", issues=[],
    )
    first = Observation(name="Shogin", raw_name="Shogin", confidence=0.91, **common)
    second = Observation(name="Shogun", raw_name="Shogun", confidence=0.96, **common)
    result = merge_observations([first, second])
    assert len(result) == 1
    assert "conflicting name spellings" in result[0].issues


def test_merge_reconciles_a_strong_rank_sequence():
    observations = []
    for rank in range(1, 7):
        read_rank = 1 if rank == 4 else rank
        observations.append(
            Observation(
                name=f"Member {rank}", points=1_000_000 - rank, rank=read_rank,
                raw_name=f"Member {rank}", raw_points=str(1_000_000 - rank), raw_rank=str(read_rank),
                confidence=0.95, timestamp_seconds=float(rank), frame_index=rank,
                source_frame=f"{rank}.jpg", issues=[],
            )
        )
    results = merge_observations(observations)
    assert [result.rank for result in results] == list(range(1, 7))
    assert results[3].review is True


def test_point_conflict_prefers_repeated_rank_evidence():
    observations = [
        Observation(
            name="Demon6666", points=58_068_559, rank=None, raw_name="Demon6666",
            raw_points="58,068,559", raw_rank="", confidence=0.90,
            timestamp_seconds=1.0, frame_index=1, source_frame="1.jpg", issues=[],
        ),
        Observation(
            name="Demon6666", points=35_589_083, rank=16, raw_name="Demon6666",
            raw_points="35,589,083", raw_rank="16", confidence=0.98,
            timestamp_seconds=2.0, frame_index=2, source_frame="2.jpg", issues=[],
        ),
    ]
    assert merge_observations(observations)[0].points == 35_589_083
