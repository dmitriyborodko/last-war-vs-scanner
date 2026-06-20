from vsparser.models import MemberResult, OCRToken
from vsparser.multilingual import (
    RecognitionCandidate,
    Script,
    is_right_to_left,
    scripts_in_text,
    select_name_candidate,
)
from vsparser.parser import normalize_name, parse_observations
from vsparser.roster import reconcile_results


def test_script_detection_covers_supported_families():
    assert scripts_in_text("Nguyễn Đặng") == {Script.LATIN}
    assert scripts_in_text("Алексей") == {Script.CYRILLIC}
    assert scripts_in_text("联盟") == {Script.CHINESE}
    assert scripts_in_text("النجوم") == {Script.ARABIC}
    assert scripts_in_text("42,089") == {Script.NUMERIC}


def test_candidate_selection_combines_confidence_script_and_roster():
    candidates = [
        RecognitionCandidate("Nguyen Dang", 0.96, "latin"),
        RecognitionCandidate("Nguyễn Đặng", 0.88, "latin"),
        RecognitionCandidate("Nguyén Däng", 0.91, "default"),
    ]
    selected = select_name_candidate(candidates, {"Nguyễn Đặng": []})
    assert selected is not None
    assert selected.text == "Nguyễn Đặng"


def test_arabic_is_preserved_as_logical_unicode_and_detected_rtl():
    name = "فريق النجوم ٧"
    assert normalize_name(name) == name
    assert is_right_to_left(name)
    assert not is_right_to_left("Alliance 7")


def test_parser_joins_separate_arabic_boxes_in_logical_rtl_order():
    def token(text, left, right):
        return OCRToken(text, 0.95, left, 100, right, 120)

    tokens = [token("النجوم", 300, 390), token("فريق", 400, 460), token("1,234,567", 700, 820)]
    observations = parse_observations(tokens, (0, 0, 900, 500), 900, 500, 1.0, 1, "frame.jpg")
    assert observations[0].name == "فريق النجوم"
    assert observations[0].points == 1_234_567


def test_roster_reconciliation_preserves_multilingual_canonical_names():
    result = MemberResult(
        name="فريق النجوم", points=100, rank=1, raw_name="فريق النجوم",
        raw_points="100", raw_rank="1", confidence=0.9, review=False,
        issues=[], timestamps=[1.0], source_frames=["frame.jpg"], observation_count=1,
    )
    reconciled = reconcile_results([result], {"فريق النجوم": [], "Nguyễn Đặng": []})
    assert reconciled[0].name == "فريق النجوم"
    assert reconciled[1].name == "Nguyễn Đặng"
