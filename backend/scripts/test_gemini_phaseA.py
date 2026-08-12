"""Phase A harness: Gemini Vision architectural interpretation (live).

Tests the provider against the project's in-repo stadium-like synthetic sheet
(the closest available fixture to the stadium drawing from the review video —
the exact image is not committed to the repo yet). Reports the structured
output, latency, cache behavior and provider limitations.

Run:
  python scripts/test_gemini_phaseA.py
"""
import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\asus\Downloads\crowdflow\backend")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(r"C:\Users\asus\Downloads\crowdflow\backend\.env"), override=False)

os.environ.setdefault("FLORENCE_ENABLED", "1")
os.environ.setdefault(
    "FLORENCE_MODEL_PATH", r"C:\Users\asus\Downloads\crowdflow\backend\models\florence-2-large"
)
os.environ["BLUEPRINT_GEMINI_ENABLED"] = "1"
os.environ["GEMINI_VISION_CACHE"] = "1"

from PIL import Image  # noqa: E402

from app.blueprint import pipeline  # noqa: E402
from app.blueprint.perception.gemini_provider import GeminiVisionProvider  # noqa: E402
from scripts.bench_ocr_gates import sheet_stadium_hatch  # noqa: E402

REPORT = Path(r"C:\Users\asus\Downloads\crowdflow\backend\reports\gemini_phaseA.json")


def summarize(analysis) -> dict:
    doc = analysis.document
    region_types = [r.type for r in analysis.regions]
    opening_types = [o.type for o in analysis.openings]
    return {
        "document": {
            "type": doc.type.value,
            "venue_type": doc.venue_type,
            "level": doc.level,
            "orientation": doc.orientation,
            "scale_evidence": doc.scale_evidence,
            "confidence": doc.confidence,
            "reasoning": doc.reasoning[:400],
        },
        "n_regions": len(analysis.regions),
        "n_openings": len(analysis.openings),
        "n_connections": len(analysis.connections),
        "n_uncertain": len(analysis.uncertain_elements),
        "region_types": sorted(set(region_types)),
        "opening_types": sorted(set(opening_types)),
        "regions": [r.model_dump() for r in analysis.regions[:12]],
        "openings": [o.model_dump() for o in analysis.openings[:12]],
        "connections": [c.model_dump() for c in analysis.connections[:10]],
        "uncertain_elements": [u.model_dump() for u in analysis.uncertain_elements],
    }


def main():
    data = sheet_stadium_hatch()
    img = Image.open(io.BytesIO(data))
    provider = GeminiVisionProvider()

    print(f"provider available: {provider.available()} reason: {provider.unavailable_reason!r}")

    # ---- first call (network) ------------------------------------------- #
    t0 = time.time()
    analysis = provider.analyze(img)
    t_cold = time.time() - t0

    # ---- second call (should hit disk cache) ---------------------------- #
    t1 = time.time()
    analysis2 = provider.analyze(img)
    t_cache = time.time() - t1

    if analysis is None:
        print("ANALYSIS FAILED -> Gemini returned nothing; provider fell back gracefully")
        analysis = None

        # ---- pipeline integration still verified (graceful fallback) ---- #
        res = pipeline.import_blueprint(data, filename="stadium_phaseA.png")
        print("\npipeline provider_status:", res.provider_status)
        print("pipeline GEMINI step    :", res.steps.get("GEMINI"))
        report = {
            "sheet": "stadium-stand-hatch",
            "model": os.getenv("GEMINI_VISION_MODEL", "gemini-3.1-flash-lite"),
            "analysis": None,
            "pipeline_provider_status": res.provider_status,
            "pipeline_gemini_step": res.steps.get("GEMINI"),
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print("\nreport:", REPORT)
        return

    report = {
        "sheet": "stadium-stand-hatch",
        "model": os.getenv("GEMINI_VISION_MODEL", "gemini-3.1-flash-lite"),
        "latency_cold_s": round(t_cold, 2),
        "latency_cached_s": round(t_cache, 2),
        "cache_hit": analysis2 is not None and analysis2.model_dump() == analysis.model_dump(),
        "analysis": summarize(analysis),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1), encoding="utf-8")

    a = report["analysis"]
    print(f"gemini model        : {report['model']}")
    print(f"latency             : cold {report['latency_cold_s']}s  cached {report['latency_cached_s']}s")
    print(f"document type       : {a['document']['type']} (conf {a['document']['confidence']}, venue {a['document']['venue_type']})")
    print(f"regions             : {a['n_regions']} -> {a['region_types']}")
    print(f"openings            : {a['n_openings']} -> {a['opening_types']}")
    print(f"connections         : {a['n_connections']}")
    print(f"uncertain           : {a['n_uncertain']}")
    print("reasoning           :", a["document"]["reasoning"][:300])
    for r in analysis.regions[:6]:
        print(f"  region {r.id} {r.type} conf={r.confidence:.2f} label={r.label} bbox={r.approximate_bbox}")
    for o in analysis.openings[:6]:
        print(f"  opening {o.id} {o.type} conf={o.confidence:.2f} label={o.label} pos={o.approximate_position}")

    # ---- pipeline integration ------------------------------------------- #
    res = pipeline.import_blueprint(data, filename="stadium_phaseA.png")
    print("\npipeline provider_status:", res.provider_status)
    print("pipeline GEMINI step    :", res.steps.get("GEMINI"))
    report["pipeline_provider_status"] = res.provider_status
    report["pipeline_gemini_step"] = res.steps.get("GEMINI")
    REPORT.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("\nreport:", REPORT)


if __name__ == "__main__":
    main()