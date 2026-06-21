from desktop import TUTORIAL_MARKER, mark_first_launch_tip_seen, should_show_first_launch_tip


def test_first_launch_tip_is_marked_seen_after_display(tmp_path):
    data_dir = tmp_path / "data"

    assert should_show_first_launch_tip(data_dir)
    mark_first_launch_tip_seen(data_dir)
    assert (data_dir / TUTORIAL_MARKER).is_file()
    assert not should_show_first_launch_tip(data_dir)


def test_first_launch_tip_remains_eligible_when_state_cannot_be_persisted(tmp_path):
    data_file = tmp_path / "data"
    data_file.write_text("not a directory", encoding="utf-8")

    mark_first_launch_tip_seen(data_file)

    assert should_show_first_launch_tip(data_file)
