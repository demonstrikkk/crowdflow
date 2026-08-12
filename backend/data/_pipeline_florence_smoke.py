import os
from io import BytesIO

from PIL import Image, ImageDraw

os.environ["FLORENCE_ENABLED"] = "1"

from app.blueprint import pipeline
from app.models import DetectionKind


def build():
    img = Image.new("RGB", (1200, 800), "white")
    d = ImageDraw.Draw(img)
    # footprint
    d.rectangle([80, 80, 1120, 720], outline=(30, 30, 30), width=8)
    # interior wall with gap (door)
    d.line([(600, 88), (600, 320)], fill=(30, 30, 30), width=6)
    d.line([(600, 420), (600, 712)], fill=(30, 30, 30), width=6)
    # interior region divider
    d.line([(200, 400), (1000, 400)], fill=(30, 30, 30), width=4)
    # stadium-like hatched block
    for i in range(18):
        d.line([(820 + i * 12, 460), (950 + i * 12, 700)], fill=(60, 60, 60), width=2)
    # labels
    d.text((150, 96), "GATE A", fill=(10, 10, 10))
    d.text((640, 96), "GATE B", fill=(10, 10, 10))
    d.text((150, 430), "CONCOURSE", fill=(10, 10, 10))
    d.text((820, 420), "SEATING BLOCK 14", fill=(10, 10, 10))
    d.text((240, 700), "STAIRS", fill=(10, 10, 10))
    # dimension + scale bar
    d.text((500, 745), "SCALE 1:500", fill=(10, 10, 10))
    return img


img = build()
buf = BytesIO()
img.save(buf, format="PNG")

print("importing with FLORENCE_ENABLED=1 ...")
res = pipeline.import_blueprint(buf.getvalue(), "florence_smoke.png")
print("-> venue", res.venue.id, "| confidence", res.confidence, "| degraded", res.degraded, "| level", res.degradation_level)
print("steps:", res.steps.get("OCR"), "|", res.steps.get("SCALE", "n/a"))
print("image_meta: WxH m =", res.image.width_m, "x", res.image.height_m, "m  (m/px =", res.image.scale_m_per_px, ")")
print("openings:", [(o.id, o.type, o.metadata.get("label")) for o in res.spatial.openings if o.type != "DOOR"][:10])
print("structures:", [(s.type, s.metadata.get("label")) for s in res.spatial.structures if s.type in ("SEATING", "CONCOURSE", "FIELD", "ROOM", "STAIR", "ZONE")])
print("unresolved:", res.report.unresolved[:10] if res.report else None)
print("OCR texts:", sorted({d.text for d in res.detections if d.kind == DetectionKind.TEXT})[:20])