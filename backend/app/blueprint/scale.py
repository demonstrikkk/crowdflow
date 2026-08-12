"""Scale / dimension extraction from blueprint text + ink (Phase 2B).

The default conversion uses a 0.6 m/px estimate (``coordinates``); this module
recovers a real pixel->metre scale from the drawing itself when the evidence
is readable:

  1. **Scale bar** (highest confidence): a horizontal dark run (the bar) near a
     dimension label that carries a numeric value with ``m`` units. Then
     ``m_per_px = value_m / bar_length_px``.
  2. **``SCALE 1:N`` text** (order-of-magnitude): the classic title-block
     annotation. Combined with a paper-size assumption once; flagged so the
     consumer (and the benchmark report) treats it as approximate.

Everything is defensive: no cv2/torch -> no hint; ambiguous input -> no hint.
The caller keeps ``estimate_dimensions_m``'s defaults when this returns None.
"""
from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

from ..models import Detection

_SCALE_RE = re.compile(r"\bscale\s*\.?\s*1\s*[:/]?\s*(\d{2,5})\b", re.IGNORECASE)
_DIM_M_RE = re.compile(r"(\d{1,5}(?:[.,]\d+)?)\s*(m|mtr|mtrs|metre|metres|meter|meters)\b", re.IGNORECASE)
_BARE_NUM_RE = re.compile(r"^\d{1,5}$")

# horizontal ink-run search window around a dimension label
_RUN_MARGIN_X = 260
_RUN_MARGIN_Y = 12
_MIN_BAR_PX = 24
_MIN_BAR_LEN_RATIO = 0.01
_MAX_BAR_LEN_RATIO = 2.0


@dataclass
class ScaleHint:
    meters_per_px: float
    confidence: str  # "high" (scale bar) | "low" (SCALE 1:N)
    note: str


def _cv2():
    return importlib.util.find_spec("cv2")


def _bbox(d: Detection) -> Optional[Tuple[float, float, float, float]]:
    return d.geometry.bbox if d.geometry.bbox else None


def estimate_scale(
    text_detections: List[Detection], image: Image.Image
) -> Optional[ScaleHint]:
    """Return the best supported scale hint, or None."""
    bar = _scale_bar_hint(text_detections, image)
    if bar is not None:
        return bar
    textual = _scale_text_hint(text_detections, image)
    if textual is not None:
        return textual
    return None


def _scale_text_hint(
    text_detections: List[Detection], image: Image.Image
) -> Optional[ScaleHint]:
    """``SCALE 1:N`` -> m_per_px under a standard A0/A1 paper assumption."""
    for d in text_detections:
        if not d.text:
            continue
        m = _SCALE_RE.search(d.text)
        if not m:
            continue
        ratio = int(m.group(1))
        if not (50 <= ratio <= 2000):
            continue
        w, h = image.size
        long_edge = max(w, h)
        # assume a drawing on A1 landscape (long edge 841 mm) or A0 (1189 mm)
        paper_long_m = 1.189 if long_edge >= 1100 else 0.841
        hint = paper_long_m * ratio / long_edge
        if not (0.02 <= hint <= 2.0):
            continue
        return ScaleHint(
            round(hint, 4), "low",
            f"scale text '{d.text.strip()}' (1:{ratio}) under A{'0' if paper_long_m > 1 else '1'} paper assumption",
        )
    return None


def _scale_bar_hint(
    text_detections: List[Detection], image: Image.Image
) -> Optional[ScaleHint]:
    """Dimension label + adjacent horizontal ink run -> precise m_per_px."""
    if _cv2() is None:
        return None
    import cv2

    arr = np.asarray(image.convert("L"))
    _, ink = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    for d in text_detections:
        box = _bbox(d)
        if box is None or not d.text:
            continue
        value_m = _dim_value_m(d.text)
        if value_m is None:
            continue
        x0, y0, x1, y1 = [int(round(v)) for v in box]
        run = _longest_horizontal_run(ink, x0, y0 - _RUN_MARGIN_Y, x1, y1 + _RUN_MARGIN_Y, margin_x=_RUN_MARGIN_X)
        if run is None:
            continue
        length_px = run[1] - run[0]
        hint = value_m / length_px
        if not (_MIN_BAR_LEN_RATIO <= hint <= _MAX_BAR_LEN_RATIO):
            continue
        return ScaleHint(
            round(hint, 4), "high",
            f"dimension label '{d.text.strip()}' = {value_m:g}m over {length_px}px ({round(hint,3):g} m/px)",
        )
    return None


def _dim_value_m(text: str) -> Optional[float]:
    """Numeric value in metres from a label with a unit (or bare number)."""
    upper = text.upper()
    m = _DIM_M_RE.search(upper)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            return None
    if _BARE_NUM_RE.match(text.strip()):
        # unitless bar label: assume metres (architectural convention) only
        # when the label is short enough to be a bar annotation (not a gate id)
        try:
            v = float(text.strip())
        except ValueError:
            return None
        return v if 1 <= v <= 300 else None
    return None


def _longest_horizontal_run(
    ink: np.ndarray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    margin_x: int,
) -> Optional[Tuple[float, float]]:
    """Longest horizontal dark run in a band of rows near ``(x0..x1, y0..y1)``."""
    h, w = ink.shape
    if y1 - y0 < 1:
        return None
    y0 = max(0, y0)
    y1 = min(h - 1, y1)
    band = ink[y0 : y1 + 1, x0 - margin_x : x1 + margin_x].astype(bool)
    if band.size == 0:
        return None
    best = None
    for row in range(band.shape[0]):
        line = band[row]
        start = None
        for i, on in enumerate(line):
            if on and start is None:
                start = i
            elif not on and start is not None:
                ln = i - start
                if ln >= _MIN_BAR_PX and (best is None or ln > best[0]):
                    best = (ln, row, start, i)
                start = None
        if start is not None:
            ln = len(line) - start
            if ln >= _MIN_BAR_PX and (best is None or ln > best[0]):
                best = (ln, row, start, len(line))
    if best is None:
        return None
    ln, row, s, e = best
    base_x = x0 - margin_x
    return (base_x + s, base_x + e)