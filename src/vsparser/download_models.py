from __future__ import annotations

import shutil

from .ocr import MODEL_NAMES, default_model_dir


def main() -> None:
    try:
        from paddlex.inference.utils.official_models import official_models
    except ImportError as error:
        raise SystemExit("Install requirements.txt before downloading OCR models.") from error

    root = default_model_dir().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for model_name in dict.fromkeys(MODEL_NAMES.values()):
        target = root / model_name
        print(f"Preparing {model_name} in {target}")
        source = official_models.get_model_path(model_name)
        shutil.copytree(source, target, dirs_exist_ok=True)
    print(f"Models ready. Processing can now remain offline: {root}")


if __name__ == "__main__":
    main()
