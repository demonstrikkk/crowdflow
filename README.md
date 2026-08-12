# CROWD FLOW

An interactive **venue digital twin** and crowd-flow decision simulator.

Upload or define a venue, simulate people moving through it, introduce
real-world scenarios, watch problems emerge, test interventions, and discover
the safest/fastest operational response. The simulation is the product — the
interface is a single operational workspace, not a dashboard.

## Features

- **Agent-based pedestrian simulation** — people move through a directed graph venue via congestion-aware A* routing; every displayed metric comes from the deterministic engine, never invented by AI
- **Event phases** — ENTRY → PEAK → INTERVAL → EXIT_SURGE with staggered arrival and departure waves
- **Weather & incidents** — HEAVY_RAIN, HAIL, HEAT, FOG, FIRE, SECURITY, STRUCTURAL events with capacity/speed modifiers and hazard spreading
- **Risk & bottleneck detection** — per-tick scoring (utilisation, density, queue length, trend) with time-to-critical prediction
- **10 intervention types** — REDIRECT, CHANGE_GATE, OPEN/CLOSE_CORRIDOR, USE_ALTERNATE_EXIT, ADJUST_ROUTING, EMERGENCY_RESPONSE, INCREASE_CAPACITY, ADD_INCIDENT, SET_WEATHER — applied live to a running simulation
- **Counterfactual comparison** — fork the current simulation, apply an intervention, run a clone in parallel, compare real metric deltas side-by-side
- **Optimization engine** — tries multiple interventions against clone simulations and reports improvement scores
- **AI natural-language interface** — Groq (llama-3.3-70b-versatile) or Gemini (gemini-2.5-flash); parses NL commands into validated scenario deltas, explains simulations, suggests variations — never simulates people
- **Blueprint import** — upload a floor-plan image → CV geometry detection → OCR text labels → semantic classification → spatial model → navigation graph → validated venue, with a multi-step review UI
- **2.5D isometric + 3D visualization** — SVG isometric canvas with zoom levels (venue / surround / network) and a Three.js 3D venue twin
- **External environment** — bundled road network (ring road + arterials + feeder roads per gate) with optional live OpenStreetMap via Overpass API
- **Crowd vision** — image upload → Hugging Face DETR object detection → people count and density estimate (privacy-first, no face recognition)

## Architecture

```
VENUE
  ↓
VENUE DIGITAL TWIN            (2.5D isometric graph canvas + Three.js 3D view)
  ↓
SURROUNDING ENVIRONMENT       (bundled road network + live OpenStreetMap)
  ↓
CROWD + SCENARIO
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
| Frontend    | React 19 + TypeScript + Vite 8 + Tailwind CSS 4 + Three.js (React Three Fiber) + Framer Motion + Recharts |
| Backend     | FastAPI + Pydantic v2 (Python 3.11) |
| Simulation  | NetworkX + NumPy (agent pipeline, density, capacity, routing) |
| Blueprint   | Pillow/NumPy geometry; optional OpenCV + Tesseract + PyMuPDF |
| Vision      | Hugging Face Inference API (DETR crowd count, token-gated) |
| Maps        | Bundled offline network; optional live OpenStreetMap (Overpass) |
| AI          | Groq or Gemini — LLM parses/explains, never simulates people |
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

## Project structure

```
backend/
  app/
    main.py              # FastAPI entry — 7 routers + health endpoints
    models.py            # Pydantic v2 schemas (venues, scenarios, simulation, vision, blueprint)
    storage.py           # SQLite persistence, seeded from data/*.json
    engine/              # simulation engine, routing, predictors, environment, vision
    ai/                  # LLM providers (Groq, Gemini), NL parsing, explanation, suggestions
    blueprint/           # image → venue pipeline (geometry, OCR, classify, spatial, navigation)
    spatial/             # coordinate conversion, spatial model derivation
    routers/             # venues, scenarios, simulation, vision, environment, ai, blueprint
  data/                  # demo venue + 6 preconfigured scenarios
frontend/
  src/
    App.tsx              # shell with mode rail (simulate, investigate, intervene, compare)
    views/               # CreateTwin, VenueBuilder, ScenarioBuilder, BlueprintReview
    components/
      shell/             # Rail sidebar, Settings
      workspace/         # Instrument canvas, 3D view, timeline, panels, command bar, status
    store/               # SimulationContext (global state, WebSocket, playback)
    lib/                 # API client, TypeScript types, formatters
```

## Quality

- Backend: `venv\Scripts\python.exe -m pytest -q` → **107 passed**
- Frontend: `npm run build` (tsc + vite) and `npm run lint` (oxlint) pass

## Docs

- `docs/ARCHITECTURE_AUDIT.md` — phase 0 audit and module mapping
- `docs/REBUILD_PLAN.md` — surgical extension plan and guardrails
