import ast
import json
from pathlib import Path

import pytest

from vsparser import localization


def test_english_catalog_entries_include_translator_context():
    path = Path(localization.__file__).with_name("locales") / "en.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))

    assert catalog
    assert all(entry.get("translation") for entry in catalog.values())
    assert all(entry.get("description") for entry in catalog.values())


def test_all_static_translation_calls_exist_in_english_catalog():
    root = Path(__file__).parents[1]
    path = Path(localization.__file__).with_name("locales") / "en.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    sources = [root / "app.py", root / "desktop.py", root / "src" / "vsparser" / "pipeline.py"]
    used = set()
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                used.add(node.args[0].value)

    assert used <= catalog.keys()


def test_locale_falls_back_from_region_to_language(tmp_path, monkeypatch):
    (tmp_path / "de.json").write_text(
        json.dumps({"Ready": {"translation": "Bereit", "description": "Idle status."}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(localization, "LOCALES_DIR", tmp_path)
    localization.load_catalog.cache_clear()

    assert localization.load_catalog("de_AT")["Ready"]["translation"] == "Bereit"

    localization.load_catalog.cache_clear()


def test_translation_formats_named_values(monkeypatch):
    monkeypatch.setattr(
        localization,
        "load_catalog",
        lambda language=None: {
            "Saved {count}": {"translation": "Stored {count}", "description": "Test status."}
        },
    )

    assert localization.tr("Saved {count}", count=3) == "Stored 3"


def test_invalid_catalog_entry_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "en.json").write_text(
        json.dumps({"Ready": {"translation": "Ready"}}), encoding="utf-8"
    )
    monkeypatch.setattr(localization, "LOCALES_DIR", tmp_path)
    localization.load_catalog.cache_clear()

    with pytest.raises(ValueError, match="needs a translation and description"):
        localization.load_catalog("en")

    localization.load_catalog.cache_clear()
