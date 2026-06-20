import desktop
from desktop import ParserWindow, SLOTS, aggregate_push_rows, format_points


class FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def get_children(self):
        return tuple(range(len(self.rows)))

    def item(self, item, field):
        assert field == "values"
        return self.rows[item]


def test_points_use_the_locale_thousands_separator(monkeypatch):
    calls = []

    def fake_format_string(pattern, value, grouping=False):
        calls.append((pattern, value, grouping))
        return "42.089.581"

    monkeypatch.setattr(desktop.locale, "format_string", fake_format_string)

    assert format_points(42_089_581) == "42.089.581"
    assert calls == [("%d", 42_089_581, True)]
    assert format_points(None) == ""


def test_table_text_copies_only_rank_name_and_points():
    table = FakeTable([(1, "Alice", 120, "0.950", "low confidence")])

    assert ParserWindow._table_text(table) == "Rank\tName\tPoints\n1\tAlice\t120"


def test_week_tables_are_copied_side_by_side_without_diagnostic_columns():
    tables = {slot: FakeTable([]) for slot in SLOTS}
    tables["Day 1"] = FakeTable([
        (1, "Alice", 120, "0.950", "low confidence"),
        (2, "Bob", 80, "0.900", ""),
    ])
    tables["Day 2"] = FakeTable([(1, "Cara", 100, "0.980", "")])

    lines = ParserWindow._week_tables_text(tables).splitlines()

    assert lines[0].split("\t")[:7] == ["Day 1", "", "", "", "Day 2", "", ""]
    assert lines[1].split("\t")[:7] == ["Rank", "Name", "Points", "", "Rank", "Name", "Points"]
    assert lines[2].split("\t")[:7] == ["1", "Alice", "120", "", "1", "Cara", "100"]
    assert lines[3].split("\t")[:7] == ["2", "Bob", "80", "", "", "", ""]
    assert "Confidence" not in lines[1]
    assert "Issues" not in lines[1]


def test_push_rows_sum_only_selected_days_and_recalculate_ranks():
    rows = {
        "Day 1": [
            {"name": "Alice", "points": 100},
            {"name": "Bob", "points": 80},
        ],
        "Day 2": [{"name": "alice", "points": 50}],
        "Day 3": [{"name": "Bob", "points": 1_000}],
    }

    result = aggregate_push_rows(rows, {"Day 1": True, "Day 2": True, "Day 3": False})

    assert [(row["rank"], row["name"], row["points"]) for row in result] == [
        (1, "Alice", 150),
        (2, "Bob", 80),
    ]
