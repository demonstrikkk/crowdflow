import os
from io import BytesIO

from PIL import Image, ImageDraw

os.environ["FLORENCE_ENABLED"] = "1"
os.environ["FLORENCE_MODEL_PATH"] = r"C:\Users\asus\Downloads\crowdflow\backend\models\florence-2-large"

from app.blueprint import pipeline, semantic
from app.models import DetectionKind


def build():
    img = Image.new("RGB", (1200, 800), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([80, 80, 1120, 720], outline=(30, 30, 30), width=8)
    d.line([(600, 88), (600, 320)], fill=(30, 30, 30), width=6)
    d.line([(600, 420), (600, 712)], fill=(30, 30, 30), width=6)
    d.line([(200, 400), (1000, 400)], fill=(30, 30, 30), width=4)
    for i in range(18):
        d.line([(820 + i * 12, 460), (950 + i * 12, 700)], fill=(60, 60, 60), width=2)
    d.text((150, 96), "GATE A", fill=(10, 10, 10))
    d.text((640, 96), "GATE B", fill=(10, 10, 10))
    d.text((150, 430), "CONCOURSE", fill=(10, 10, 10))
    d.text((820, 420), "SEATING BLOCK 14", fill=(10, 10, 10))
    d.text((240, 700), "STAIRS", fill=(10, 10, 10))
    d.text((500, 745), "SCALE 1:500", fill=(10, 10, 10))
    return img


img = build()
buf = BytesIO()
img.save(buf, format="PNG")
pre = pipeline.preprocess.preprocess(buf.getvalue(), "dbg.png")
stage = pipeline.detect_blueprint(buf.getvalue(), "dbg.png")
print("OCR provider:", stage.ocr_provider, "| image", pre.width_px, "x", pre.height_px)
for d in stage.detections:
    if d.kind == DetectionKind.TEXT:
        print("TEXT", repr(d.text), "bbox", d.geometry.bbox)
    elif d.kind == DetectionKind.GATE:
        print("GATE", d.geometry.point, "bbox", d.geometry.bbox, "side", d.metadata.get("side"), "w", d.metadata.get("width_px"))
print("---- regions ----")
for d in stage.detections:
    if d.kind == DetectionKind.REGION:
        print("REGION bbox", d.geometry.bbox, "conf", d.confidence)
print("---- semantic ----")
sem = semantic.interpret(stage.detections, pre.width_px, pre.height_px)
for s in sem.structures:
    print("STRUCT", s["kind"], "label:", s.get("label"), "centroid", s["centroid_px"])
for g in sem.gates:
    print("GATE-SEM", g.get("id"), g.get("kind"), "label:", g.get("label"), "pos", g.get("position"))