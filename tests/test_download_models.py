from pathlib import Path
from types import SimpleNamespace

from vsparser import download_models


def test_download_models_copies_official_packages(monkeypatch, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    destination = tmp_path / "models"
    requested = []

    def get_model_path(name: str) -> str:
        requested.append(name)
        source = cache / name
        source.mkdir(parents=True)
        (source / "inference.yml").write_text("Global: {}", encoding="utf-8")
        return str(source)

    official_models = SimpleNamespace(get_model_path=get_model_path)
    module = SimpleNamespace(official_models=official_models)
    monkeypatch.setitem(__import__("sys").modules, "paddlex.inference.utils.official_models", module)
    monkeypatch.setattr(download_models, "default_model_dir", lambda: destination)

    download_models.main()

    expected = list(dict.fromkeys(download_models.MODEL_NAMES.values()))
    assert requested == expected
    assert all((destination / name / "inference.yml").is_file() for name in expected)
