# CROWD FLOW

An interactive **venue digital twin** and crowd-flow decision simulator.

Upload or define a venue, simulate people moving through it, introduce
real-world scenarios, watch problems emerge, test interventions, and discover
the safest/fastest operational response. The simulation is the product — the
interface is a single operational workspace, not a dashboard.

## Architecture

```
VENUE
  ↓
VENUE DIGITAL TWIN            (2.5D isometric graph canvas)
  ↓
SURROUNDING ENVIRONMENT       (bundled road network + live OpenStreetMap)
  ↓
CROWD
  ↓
SCENARIO
  ↓
SIMULATION                    (deterministic, seeded Python engine)
  ↓
OBSERVATION → BOTTLENECK / RISK
  ↓
INTERVENTION → COUNTERFACTUAL SIMULATION
  ↓
COMPARISON → RECOMMENDATION
```

| Layer       | Technology |
|-------------|------------|
| Frontend    | React 19 + TypeScript + Vite 8 + Tailwind 4 |
| Backend     | FastAPI + Pydantic v2 (Python 3.11) |
| Simulation  | NetworkX + NumPy (agent pipeline, density, capacity, routing) |
| Blueprint   | Pillow/NumPy geometry; optional OpenCV + Tesseract + PyMuPDF |
| Vision      | Hugging Face Inference API (DETR crowd count, token-gated) |
| Maps        | Bundled offline network; optional live OpenStreetMap (Overpass) |
| AI          | optional — LLM parses/explains, never simulates people |
| Persistence | SQLite (`backend/data/crowdflow.db`) |
| Deployment  | Vercel (frontend) + Render (backend) |

## Running

```bash
# backend  (http://localhost:8000, docs at /docs)
cd backend
venv\Scripts\python.exe -m uvicorn app.main:app --reload

# frontend (http://localhost:5173)
cd frontend
npm run dev
```

## Gap status

| Gap | Scope | Status |
|-----|-------|--------|
| C   | 2.5D/isometric venue presentation (`InstrumentCanvas`) | Done |
| D   | External environment: bundled roads + live OSM fallback, external congestion model + `SimulationState.external`, `/api/environment` router, frontend overlay + venue/surround/network zoom levels | Done |
| E   | Blueprint import: layered pipeline (geometry → OCR → classify → graph → validated venue), `POST /api/blueprint/import`, frontend import UI in `VenueBuilderView` | Done |

Optional blueprint engines (`opencv-python-headless`, `PyMuPDF`, `pytesseract`)
are listed in `backend/requirements-optional.txt`; without them the pipeline
degrades to heuristic geometry and reports `degraded: true`.

## Quality gates

- Backend: `venv\Scripts\python.exe -m pytest -q` → **107 passed**
- Frontend: `npm run build` (tsc + vite) and `npm run lint` (oxlint) pass

Docs: `docs/ARCHITECTURE_AUDIT.md` (phase 0) and `docs/REBUILD_PLAN.md`
