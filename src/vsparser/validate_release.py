from __future__ import annotations

import importlib.util

from .ocr import MODEL_NAMES, default_model_dir


REQUIRED_PACKAGES = ("cv2", "numpy", "onnxruntime", "paddle", "paddleocr", "tkinterdnd2")


def main() -> None:
    errors = []
    for package in REQUIRED_PACKAGES:
        if importlib.util.find_spec(package) is None:
            errors.append(f"missing packaged dependency: {package}")

    root = default_model_dir().resolve()
    for model_name in dict.fromkeys(MODEL_NAMES.values()):
        path = root / model_name
        if not path.is_dir() or not any(path.iterdir()):
            errors.append(f"missing bundled OCR model: {path}")

    if errors:
        raise SystemExit("Release validation failed:\n- " + "\n- ".join(errors))
    print(f"Release OCR dependencies and {len(set(MODEL_NAMES.values()))} models are present.")


if __name__ == "__main__":
    main()
