"""Blueprint image preprocessing.

Accepts PNG / JPG / WEBP / BMP (via Pillow) and PDF (via PyMuPDF when
installed). Outputs a *normalised* raster plus an image descriptor used by
every downstream stage:

  * resolution normalised (long edge <= 1600 px) with the scale tracked;
  * deskewed when the drawing is tilted (OpenCV min-area rectangle);
  * light denoise so line/region extraction is stable;
  * original aspect ratio preserved.

The pixel -> venue-metre conversion lives in ``app.spatial.coordinates``;
this module only establishes the frame (pixel size + metre size).
"""
from __future__ import annotations

import importlib.util
import io
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
from PIL import Image, ImageOps

_MAX_LONG_EDGE = 1600


def _fitz_available() -> bool:
    return importlib.util.find_spec("fitz") is not None or importlib.util.find_spec("pymupdf") is not None


def _is_pdf(data: bytes) -> bool:
    return data[:5].lstrip() == b"%PDF-"


@dataclass
class PreprocessedImage:
    image: Image.Image  # RGB, normalised long edge
    filename: str
    format: str  # png | jpeg | pdf | webp | bmp
    page: int  # selected page (1-based)
    pages: int  # total pages (PDFs > 1)
    deskew_deg: float = 0.0
    raw_width_px: int = 0
    raw_height_px: int = 0
    resize_ratio: float = 1.0  # normalised size / original size
    notes: List[str] = field(default_factory=list)

    @property
    def width_px(self) -> int:
        return self.image.width

    @property
    def height_px(self) -> int:
        return self.image.height


def _render_pdf_page(data: bytes, page_index: int) -> Optional[Image.Image]:
    try:
        if _fitz_available():
            import fitz  # PyMuPDF

            doc = fitz.open(stream=data, filetype="pdf")
            if page_index >= len(doc):
                return None
            page = doc[page_index]
            pix = page.get_pixmap(dpi=150)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            doc.close()
            return img
    except Exception:
        return None
    return None


def _deskew(img: Image.Image) -> tuple[Image.Image, float]:
    """Rotate a tilted drawing back to axis-aligned using the ink bounding box."""
    try:
        import cv2

        arr = np.asarray(img.convert("L"))
        _, ink = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        ys, xs = np.where(ink > 0)
        if len(xs) < 500:
            return img, 0.0
        rect = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        angle = rect[2]
        # cv2 minAreaRect returns angle in [-45, 0] for the "height" axis; the
        # drawing is rotated when the long edge is not axis aligned.
        if angle < -45.0:
            angle = 90.0 + angle
        if angle < -45.0:
            angle = -(90.0 + angle)
        if abs(angle) < 0.4 or abs(angle) > 8.0:
            return img, 0.0
        h, w = arr.shape
        M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
        rot = cv2.warpAffine(
            np.asarray(img), M, (w, h), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255)
        )
        return Image.fromarray(rot), round(angle, 2)
    except Exception:
        return img, 0.0


def _denoise(img: Image.Image) -> Image.Image:
    try:
        import cv2

        arr = np.asarray(img)
        arr = cv2.bilateralFilter(arr, 5, 40, 40)
        return Image.fromarray(arr)
    except Exception:
        return img


def preprocess(
    data: bytes,
    filename: str = "blueprint",
    page: int = 1,
) -> Optional[PreprocessedImage]:
    """Decode, normalise and deskew a blueprint; None when it cannot be read."""
    fmt = "pdf" if _is_pdf(data) else None
    img: Optional[Image.Image] = None
    pages = 1

    if fmt == "pdf":
        img = _render_pdf_page(data, page - 1)
        if img is None:
            return None
        pages = _pdf_page_count(data)
    else:
        try:
            img = Image.open(io.BytesIO(data))
            fmt = (img.format or "png").lower()
            img = ImageOps.exif_transpose(img)
            img.load()
        except Exception:
            return None

    img = img.convert("RGB")
    raw_w, raw_h = img.size

    long_edge = max(raw_w, raw_h)
    ratio = 1.0
    if long_edge > _MAX_LONG_EDGE:
        ratio = _MAX_LONG_EDGE / long_edge
        img = img.resize(
            (max(1, round(raw_w * ratio)), max(1, round(raw_h * ratio))),
            Image.LANCZOS,
        )

    img, angle = _deskew(img)
    img = _denoise(img)

    notes: List[str] = []
    if ratio < 1.0:
        notes.append(f"downscaled {round(ratio, 3):g} to cap the long edge at {_MAX_LONG_EDGE}px")
    if angle:
        notes.append(f"deskewed {angle:+g} deg")
    if fmt == "pdf" and pages > 1:
        notes.append(f"PDF has {pages} pages; page {page} used for reconstruction")

    return PreprocessedImage(
        image=img,
        filename=filename,
        format=fmt,
        page=page,
        pages=pages,
        deskew_deg=angle,
        raw_width_px=raw_w,
        raw_height_px=raw_h,
        resize_ratio=ratio,
        notes=notes,
    )


def _pdf_page_count(data: bytes) -> int:
    try:
        if not _fitz_available():
            return 1
        import fitz

        doc = fitz.open(stream=data, filetype="pdf")
        n = len(doc)
        doc.close()
        return max(1, n)
    except Exception:
        return 1
