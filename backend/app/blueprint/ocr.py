"""Optional OCR label extraction.

Tesseract is only used when installed (`pytesseract` + system binary). Returns
an empty list otherwise so the pipeline degrades to geometric labels.
"""
from __future__ import annotations

import importlib.util
from typing import List, Optional

from PIL import Image

_has_pytesseract: Optional[bool] = None


def _available() -> bool:
    global _has_pytesseract
    if _has_pytesseract is None:
        _has_pytesseract = importlib.util.find_spec("pytesseract") is not None
    return _has_pytesseract


def extract_labels(image: Image.Image) -> List[dict]:
    """Return OCR boxes: [{"text", "position": (x, y), "confidence"}].

    position is the centroid of the word box in image pixels.
    """
    if not _available():
        return []
    import pytesseract

    try:
        data = pytesseract.image_to_data(
            image.convert("RGB"), output_type=pytesseract.Output.DICT
        )
    except Exception:
        return []

    boxes: List[dict] = []
    n = len(data["text"])
    for i in range(n):
        text = str(data["text"][i]).strip()
        conf = float(data["conf"][i])
        if not text or conf < 30:
            continue
        if data["left"][i] <= 0 or data["top"][i] <= 0:
            continue
        x = int(data["left"][i] + data["width"][i] / 2)
        y = int(data["top"][i] + data["height"][i] / 2)
        boxes.append({"text": text, "position": (x, y), "confidence": conf / 100.0})
    return boxes
