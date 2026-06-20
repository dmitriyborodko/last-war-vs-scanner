from __future__ import annotations

from .ocr import MODEL_NAMES, default_model_dir


def main() -> None:
    try:
        from paddleocr import TextRecognition
    except ImportError as error:
        raise SystemExit("Install requirements.txt before downloading OCR models.") from error

    root = default_model_dir().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for model_name in dict.fromkeys(MODEL_NAMES.values()):
        target = root / model_name
        print(f"Preparing {model_name} in {target}")
        TextRecognition(model_name=model_name, model_dir=str(target), device="cpu")
    print(f"Models ready. Processing can now remain offline: {root}")


if __name__ == "__main__":
    main()
