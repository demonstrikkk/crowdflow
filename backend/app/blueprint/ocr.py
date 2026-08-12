"""Optional OCR label extraction for blueprint text.

Text perception returns the shared ``Detection`` representation (kind TEXT)
with the original bounding box, so the semantic stage can associate labels
with nearby geometry. Backends, in priority order:

  1. **Tesseract** (pytesseract + system binary) - full confidence + box.
  2. **Windows WinRT OCR** (``winsdk``, Windows 10+) - offline, no install,
     exposes text + bounding box. Per-word confidence is not exposed by the
     API, so a conservative 0.8 proxy is used and recorded in metadata.
  3. Neither available -> empty list (pipeline degrades to geometry labels).

Every backend returns ``Detection`` objects (kind TEXT) with
``geometry.type == POLYGON`` representing the word's bounding box.
"""
from __future__ import annotations

import importlib.util
from typing import List, Optional

from PIL import Image

from .perception.base import OCRProvider
from ..models import Detection, DetectionGeometry, DetectionKind, GeometryType, Point2D


def _box_detection(
    det_id: str, text: str, x0: float, y0: float, x1: float, y1: float, conf: float, source: str
) -> Detection:
    return Detection(
        id=det_id,
        kind=DetectionKind.TEXT,
        geometry=DetectionGeometry(
            type=GeometryType.POLYGON,
            polygon=[
                Point2D(x=x0, y=y0), Point2D(x=x1, y=y0),
                Point2D(x=x1, y=y1), Point2D(x=x0, y=y1),
            ],
            bbox=(x0, y0, x1, y1),
        ),
        text=text,
        confidence=max(0.05, min(1.0, conf)),
        source=source,
        metadata={"bbox": [x0, y0, x1, y1]},
    )


class TesseractOcrProvider(OCRProvider):
    id = "tesseract"
    name = "Tesseract OCR"

    def __init__(self):
        self._has = None

    @staticmethod
    def _locate_binary():
        """Point pytesseract at a system tesseract when it is not on PATH.

        Respects ``TESSERACT_CMD`` env, then probes common Windows install
        locations so `available()` works without modifying PATH.
        """
        import os

        import pytesseract

        cfg = os.environ.get("TESSERACT_CMD", "").strip()
        current = getattr(pytesseract.pytesseract, "tesseract_cmd", "") or ""
        if cfg:
            pytesseract.pytesseract.tesseract_cmd = cfg
        elif current.lower() in ("", "tesseract"):
            for cand in (
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
            ):
                if os.path.exists(cand):
                    pytesseract.pytesseract.tesseract_cmd = cand
                    break
        return pytesseract

    def available(self) -> bool:
        if self._has is None:
            try:
                pytesseract = self._locate_binary()
                self._has = bool(pytesseract.get_tesseract_version())
            except Exception:
                self._has = False
        return self._has

    def extract(self, image: Image.Image) -> List[Detection]:
        if not self.available():
            return []
        pytesseract = self._locate_binary()

        try:
            data = pytesseract.image_to_data(
                image.convert("RGB"), output_type=pytesseract.Output.DICT
            )
        except Exception:
            return []

        out: List[Detection] = []
        n = len(data["text"])
        for i in range(n):
            text = str(data["text"][i]).strip()
            if not text:
                continue
            conf = float(data["conf"][i])
            if conf < 30:
                continue
            l, t = int(data["left"][i]), int(data["top"][i])
            w, h = int(data["width"][i]), int(data["height"][i])
            if l <= 0 or t <= 0 or w <= 0 or h <= 0:
                continue
            out.append(
                _box_detection(
                    f"OCR_T{i}", text, l, t, l + w, t + h, conf / 100.0, "OCR"
                )
            )
        return out


class WinRTOcrProvider(OCRProvider):
    id = "winrt"
    name = "Windows WinRT OCR"

    def __init__(self):
        self._has = None

    def available(self) -> bool:
        if self._has is None:
            try:
                import winsdk.windows.media.ocr  # noqa: F401

                self._has = True
            except Exception:
                self._has = False
        return self._has

    def _engine(self):
        from winsdk.windows.globalization import Language
        from winsdk.windows.media.ocr import OcrEngine

        eng = OcrEngine.try_create_from_user_profile_languages()
        if eng is None:
            eng = OcrEngine.try_create_from_language(Language("en-US"))
        return eng

    def extract(self, image: Image.Image) -> List[Detection]:
        if not self.available():
            return []
        try:
            return self._run(image)
        except Exception:
            return []

    def _run(self, image: Image.Image) -> List[Detection]:
        import asyncio

        from winsdk.windows.graphics.imaging import BitmapDecoder
        from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        def _sync(coro):
            try:
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(coro)
                finally:
                    loop.close()
            except RuntimeError:
                return asyncio.run(coro)

        import io

        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        data = buf.getvalue()

        async def run() -> List[Detection]:
            stream = InMemoryRandomAccessStream()
            writer = DataWriter(stream)
            writer.write_bytes(data)
            await writer.store_async()
            stream.seek(0)
            dec = await BitmapDecoder.create_async(stream)
            bmp = await dec.get_software_bitmap_async()
            eng = self._engine()
            if eng is None:
                return []
            res = await eng.recognize_async(bmp)
            out: List[Detection] = []
            for li, line in enumerate(res.lines):
                for wi, word in enumerate(line.words):
                    text = str(word.text).strip()
                    if not text:
                        continue
                    r = word.bounding_rect
                    if r.width <= 1 or r.height <= 1:
                        continue
                    out.append(
                        _box_detection(
                            f"OCR_L{li}_W{wi}", text, r.x, r.y, r.x + r.width, r.y + r.height,
                            0.8, "OCR",
                        )
                    )
            return out

        return _sync(run())


def extract_labels(image: Image.Image) -> List[dict]:
    """Back-compat helper: OCR boxes as ``[{"text", "position", "confidence"}]``."""
    from .perception.base import get_ocr_providers

    detections: List[Detection] = []
    for provider in get_ocr_providers():
        detections = provider.extract(image)
        if detections:
            break

    boxes: List[dict] = []
    for d in detections:
        cx = d.geometry.bbox[0] + (d.geometry.bbox[2] - d.geometry.bbox[0]) / 2
        cy = d.geometry.bbox[1] + (d.geometry.bbox[3] - d.geometry.bbox[1]) / 2
        boxes.append({"text": d.text, "position": (int(cx), int(cy)), "confidence": d.confidence})
    return boxes
