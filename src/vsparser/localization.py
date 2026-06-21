from __future__ import annotations

import json
import locale
import os
from functools import lru_cache
from pathlib import Path


LOCALES_DIR = Path(__file__).with_name("locales")
DEFAULT_LANGUAGE = "en"


def _system_language() -> str:
    requested = os.environ.get("VSPARSER_LANGUAGE")
    if requested:
        return requested
    language, _encoding = locale.getlocale()
    return language or DEFAULT_LANGUAGE


def _language_candidates(language: str) -> tuple[str, ...]:
    normalized = language.replace("-", "_")
    base = normalized.split("_", 1)[0]
    return tuple(dict.fromkeys((normalized, base, DEFAULT_LANGUAGE)))


@lru_cache(maxsize=None)
def load_catalog(language: str | None = None) -> dict[str, dict[str, str]]:
    """Load the best catalog for a locale, falling back to English."""
    catalog: dict[str, dict[str, str]] = {}
    for candidate in reversed(_language_candidates(language or _system_language())):
        path = LOCALES_DIR / f"{candidate}.json"
        if not path.is_file():
            continue
        additions = json.loads(path.read_text(encoding="utf-8"))
        for source, entry in additions.items():
            if not isinstance(entry, dict) or not entry.get("translation") or not entry.get("description"):
                raise ValueError(f"Localization entry {source!r} needs a translation and description")
        catalog.update(additions)
    return catalog


def tr(source: str, /, **values: object) -> str:
    """Translate a source string and substitute its named placeholders."""
    entry = load_catalog().get(source)
    translated = entry["translation"] if entry else source
    return translated.format(**values)
