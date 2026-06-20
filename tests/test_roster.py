from pathlib import Path

from vsparser.models import MemberResult
from vsparser.roster import (
    apply_roster_alias,
    available_roster_members,
    edit_result_name,
    load_roster,
    find_most_similar_roster_name,
    match_roster_name,
    parse_member_list,
    reconcile_results,
    remember_names,
    save_member_list,
    save_roster,
)


def _stored_row(name: str, issues: str = "", points: int = 10) -> dict:
    return {"name": name, "points": points, "issues": issues, "review": bool(issues)}


def test_day_name_edit_claims_absent_member_and_removes_placeholder():
    rows = [
        _stored_row("A1ice", "not in alliance member list"),
        _stored_row("Alice", "not present in VS list; added with zero points", 0),
        _stored_row("Bob"),
    ]
    roster = {"Alice": [], "Bob": []}

    assert edit_result_name(rows, 0, "Alice", roster) == "Alice"
    assert [(row["name"], row["points"]) for row in rows] == [("Alice", 10), ("Bob", 10)]
    assert rows[0]["issues"] == ""


def test_day_name_edit_stays_local_and_flags_unknown_name():
    rows = [_stored_row("Alice")]
    assert edit_result_name(rows, 0, "Outsider", {"Alice": []}) == "Outsider"
    assert rows[0]["issues"] == "not in alliance member list"


def test_day_name_edit_accepts_selected_rows_existing_member():
    rows = [_stored_row("Alice", "not in alliance member list"), _stored_row("Bob")]
    assert edit_result_name(rows, 0, "Alice", {"Alice": [], "Bob": []}) == "Alice"
    assert rows[0]["issues"] == ""


def test_alias_assignment_refreshes_matching_week_rows_only():
    first = [
        _stored_row("A1ice", "not in alliance member list"),
        _stored_row("Alice", "not present in VS list; added with zero points", 0),
    ]
    second = [_stored_row("Alice")]

    assert available_roster_members(first, {"Alice": [], "Bob": []}) == ["Alice", "Bob"]
    assert apply_roster_alias(first, "A1ice", "Alice") is True
    assert apply_roster_alias(second, "A1ice", "Alice") is False
    assert [(row["name"], row["points"]) for row in first] == [("Alice", 10)]


def test_roster_remembers_unicode_name_and_ocr_alias(tmp_path: Path):
    path = tmp_path / "roster.json"
    remember_names(path, [{"name": "★Mïstïc★", "raw_name": "Mistic | Mystic"}])
    roster = load_roster(path)
    assert roster["★Mïstïc★"] == ["Mistic", "Mystic"]
    assert match_roster_name("Mistic", roster)[0] == "★Mïstïc★"


def test_roster_rejects_ambiguous_short_match():
    roster = {"Ann One": ["Ann"], "Ann Two": ["Ann"]}
    assert match_roster_name("Ann", roster) is None


def test_closest_roster_match_accepts_likely_ocr_damage():
    roster = {"Alice": [], "Completely Different": []}
    assert find_most_similar_roster_name("Alic3zz", roster)[0] == "Alice"


def test_closest_roster_match_rejects_unrelated_name():
    assert find_most_similar_roster_name("Outsider", {"Alice": [], "Bob": []}) is None


def test_member_list_accepts_spreadsheet_column_and_deduplicates():
    assert parse_member_list(" Alice \nBob\r\n\nALICE\nB-ob") == ["Alice", "Bob"]


def test_save_member_list_adds_removes_and_preserves_existing_aliases(tmp_path: Path):
    path = tmp_path / "roster.json"
    remember_names(path, [{"name": "Alice", "raw_name": "A1ice"}, {"name": "Removed", "raw_name": "Rernoved"}])

    assert save_member_list(path, "Alice\nNew member") == ["Alice", "New member"]
    assert load_roster(path) == {"Alice": ["A1ice"], "New member": []}


def test_save_roster_keeps_aliases_and_removes_duplicate_spellings(tmp_path: Path):
    path = tmp_path / "roster.json"

    assert save_roster(path, {" Alice ": ["A1ice", "a1ice", "Alice", ""], "Bob": ["B0b"]}) == ["Alice", "Bob"]
    assert load_roster(path) == {"Alice": ["A1ice"], "Bob": ["B0b"]}


def _result(name: str, points: int = 100) -> MemberResult:
    return MemberResult(
        name=name, points=points, rank=1, raw_name=name, raw_points=str(points), raw_rank="1",
        confidence=0.95, review=False, issues=[], timestamps=[1.0], source_frames=["frame.jpg"],
        observation_count=1,
    )


def test_reconcile_corrects_names_flags_non_members_and_adds_missing_members():
    results = [_result("Alic3zz"), _result("Outsider")]
    roster = {"Alice": [], "Bob": []}

    reconciled = reconcile_results(results, roster)

    assert [(result.name, result.points) for result in reconciled] == [
        ("Alice", 100), ("Outsider", 100), ("Bob", 0),
    ]
    assert "name corrected from alliance member list (67%)" in reconciled[0].issues
    assert reconciled[1].review is True
    assert "not in alliance member list" in reconciled[1].issues
    assert reconciled[2].review is False
    assert reconciled[2].observation_count == 0


def test_reconcile_does_nothing_without_a_roster():
    results = [_result("Anyone")]
    assert reconcile_results(results, {}) is results


def test_reconcile_reserves_exact_matches_before_closest_name_assignment():
    results = [_result("Alic3zz"), _result("Alice")]
    reconciled = reconcile_results(results, {"Alice": [], "Bob": []})

    assert reconciled[0].name == "Alic3zz"
    assert "not in alliance member list" in reconciled[0].issues
    assert reconciled[1].name == "Alice"
    assert sum(result.name == "Alice" for result in reconciled) == 1
