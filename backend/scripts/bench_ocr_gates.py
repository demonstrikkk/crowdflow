"""A/B benchmark: Florence VLM OCR vs Tesseract for blueprint gate labels.

Generates a small deterministic corpus of synthetic venue sheets with known
gate labels, runs the full import pipeline with each OCR backend, and reports:

  * recall_exact   - share of ground-truth gate labels whose text the OCR
                     engine recovered exactly (pure reading quality)
  * n_gate_dets    - CV gate detections (shared geometry baseline)
  * n_bound        - semantic gates that ended up carrying a label
  * bound_ok       - bound labels matching the ground-truth gate set
  * unresolved     - gate-like texts OCR read but the pipeline never bound

Run:
  python scripts/bench_ocr_gates.py
"""
import io
import json
import os
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, r"C:\Users\asus\Downloads\crowdflow\backend")

os.environ["FLORENCE_ENABLED"] = "1"
os.environ["FLORENCE_MODEL_PATH"] = r"C:\Users\asus\Downloads\crowdflow\backend\models\florence-2-large"

from app.blueprint import pipeline, semantic  # noqa: E402

REPORT = Path(r"C:\Users\asus\Downloads\crowdflow\backend\reports\ocr_gate_ab.json")

FONT = None
FONT_SMALL = None
for cand in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf"):
    if Path(cand).exists():
        FONT = ImageFont.truetype(cand, 22)
        FONT_SMALL = ImageFont.truetype(cand, 13)
        break
if FONT is None:
    FONT = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()

GATE_RE = re.compile(r"^(gate|turnstile|ticket|entry|entrance|exit|emergency)\b", re.IGNORECASE)


def new_sheet(w=1200, h=800) -> Image.Image:
    img = Image.new("RGB", (w, h), "white")
    return img


def walls_and_gates(d: ImageDraw.ImageDraw, x0, y0, x1, y1, w=6, gaps=()):
    """Draw a rectangle outline, skipping light gaps on each side.

    ``gaps`` = list of (side, a, b) where the wall is left open.
    """
    sides = {
        "N": [(x0, y0, x1, y0), "h"],
        "S": [(x0, y1, x1, y1), "h"],
        "W": [(x0, y0, x0, y1), "v"],
        "E": [(x1, y0, x1, y1), "v"],
    }
    for side, (coords, orient) in sides.items():
        segments = []
        cut = sorted([(g[1], g[2]) for g in gaps if g[0] == side])
        cursor = 0 if orient == "h" else 0
        length = x1 - x0 if orient == "h" else y1 - y0
        for a, b in sorted(cut):
            if a > cursor:
                segments.append((cursor, a))
            cursor = max(cursor, b)
        if cursor < length:
            segments.append((cursor, length))
        for a, b in segments:
            if orient == "h":
                d.line([(x0 + a, y0), (x0 + b, y0)], fill=(30, 30, 30), width=w)
            else:
                d.line([(x0, y0 + a), (x0, y0 + b)], fill=(30, 30, 30), width=w)


def text(d: ImageDraw.ImageDraw, xy, s, font=FONT, fill=(10, 10, 10)):
    d.text(xy, s, fill=fill, font=font)


def hatch_block(d: ImageDraw.ImageDraw, x0, y0, x1, y1, n=18, w=2, fill=(60, 60, 60)):
    for i in range(n):
        step = (x1 - x0) / max(1, n - 1)
        d.line([(x0 + i * step, y0 + i * step), (x0, y0 + i * step)], fill=fill, width=w)


def sheet_arena() -> bytes:
    img = new_sheet()
    d = ImageDraw.Draw(img)
    walls_and_gates(d, 80, 80, 1120, 720, w=6, gaps=[("N", 220, 260), ("N", 720, 760),
                                                    ("S", 420, 460), ("S", 920, 960)])
    d.line([(600, 86), (600, 340)], fill=(30, 30, 30), width=6)
    d.line([(600, 380), (600, 714)], fill=(30, 30, 30), width=6)
    hatch_block(d, 820, 420, 950, 700, n=18)
    text(d, (225, 56), "GATE A")
    text(d, (725, 56), "GATE B")
    text(d, (420, 732), "GATE C")
    text(d, (920, 732), "GATE D")
    text(d, (130, 425), "CONCOURSE")
    text(d, (700, 150), "SEATING BLOCK 14")
    text(d, (240, 700), "STAIRS")
    text(d, (500, 745), "SCALE 1:500")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def sheet_stadium_hatch() -> bytes:
    """Stadium stand pattern: hatched blocks touch the north wall between the
    two gate gaps. This is the sheet class that defeats the CV gap heuristic
    (hatch tips leak past the wall line and read as wide false gates)."""
    img = new_sheet()
    d = ImageDraw.Draw(img)
    walls_and_gates(d, 80, 80, 1120, 720, w=6, gaps=[("N", 220, 260), ("N", 760, 800)])
    hatch_block(d, 300, 90, 700, 360, n=34)
    hatch_block(d, 820, 90, 1100, 300, n=26)
    text(d, (225, 56), "GATE A")
    text(d, (765, 56), "GATE B")
    text(d, (130, 425), "CONCOURSE")
    text(d, (700, 150), "SEATING BLOCK 14")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def sheet_low_contrast() -> bytes:
    img = new_sheet()
    d = ImageDraw.Draw(img)
    walls_and_gates(d, 80, 80, 1120, 720, w=4, gaps=[("N", 420, 460)])
    text(d, (425, 60), "GATE A", font=FONT_SMALL, fill=(140, 140, 140))
    text(d, (130, 425), "CONCOURSE", font=FONT_SMALL, fill=(120, 120, 120))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


CORPUS = [
    {"name": "arena-4gates", "bytes": sheet_arena, "gt_gates": ["GATE A", "GATE B", "GATE C", "GATE D"]},
    {"name": "stadium-stand-hatch", "bytes": sheet_stadium_hatch, "gt_gates": ["GATE A", "GATE B"]},
    {"name": "low-contrast-text", "bytes": sheet_low_contrast, "gt_gates": ["GATE A"]},
]


def read_texts(dets) -> list:
    return [d.text for d in dets if getattr(d, "kind", None) and d.kind.value == "TEXT" and d.text]


def run_sheet(name, data, gt_gates, backend):
    os.environ["BLUEPRINT_OCR_BACKEND"] = backend
    result = pipeline.import_blueprint(data, filename=f"{name}.png")
    sem = semantic.interpret(result.detections, result.image.width_px, result.image.height_px)

    texts = read_texts(result.detections)
    norm = {t.lower() for t in texts}
    recall_exact = sum(1 for g in gt_gates if g.lower() in norm) / max(1, len(gt_gates))

    gate_dets = [d for d in result.detections if d.kind.value == "GATE"]
    bound = [g.get("label") for g in sem.gates if g.get("label")]
    bound_norm = {b.lower() for b in bound}
    bound_ok = sum(1 for g in gt_gates if g.lower() in bound_norm)

    unresolved = [t for t in texts if GATE_RE.match(t) and t.lower() not in bound_norm]

    return {
        "sheet": name,
        "ocr": backend,
        "gt_gates": gt_gates,
        "n_gt": len(gt_gates),
        "recall_exact": round(recall_exact, 3),
        "read_texts": texts,
        "n_gate_dets": len(gate_dets),
        "n_gates_sem": len(sem.gates),
        "n_bound": len(bound),
        "bound_labels": bound,
        "bound_ok": bound_ok,
        "unresolved": unresolved,
        "degraded": bool(result.degraded),
        "notes": [n for k, n in result.steps.items() if k.startswith("NOTE")],
    }


def main():
    os.makedirs(REPORT.parent, exist_ok=True)
    all_rows = []
    for sheet in CORPUS:
        data = sheet["bytes"]()
        for backend in ("florence", "tesseract"):
            all_rows.append(run_sheet(sheet["name"], data, sheet["gt_gates"], backend))

    report = {"rows": all_rows}
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"{'sheet':24} {'ocr':10} {'recall':7} {'gt':3} {'gateDets':8} {'bound':6} {'ok':3} {'unres':5}")
    for r in all_rows:
        print(f"{r['sheet']:24} {r['ocr']:10} {r['recall_exact']:7.2f} {r['n_gt']:<3} "
              f"{r['n_gate_dets']:<8} {r['n_bound']:<6} {r['bound_ok']:<3} {len(r['unresolved']):<5}")
    print(f"\nreport: {REPORT}")


if __name__ == "__main__":
    main()
