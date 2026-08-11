# CROWD FLOW — Architecture Audit (Phase 0)

Date: 2026-08-11
Scope: full inspection of the existing PS3 prototype at the repository root.

## 1. Summary

The existing prototype is **not** a throwaway "SaaS dashboard". It already
implements most of the PS3 core requirements and a meaningful slice of the
expanded vision:

- a **real, deterministic simulation engine** (agent pipeline, density,
  capacity, bottleneck detection, risk scoring, congestion-aware routing)
- a **counterfactual / optimize** layer that runs *real* second simulations
- a **congestion-aware routing engine** (A* with dynamic penalties)
- a **WebSocket live feed** with a compact `SimulationState` packet
- a **Hugging Face crowd-counting** vision integration (already used)
- a frontend that is already an **operational instrument workspace** (venue
  canvas, timeline scrubber, context inspector, compare mode, guided "what if"
  flow), not a card grid.

The dramatic framing of the brief ("completely abandon the generic SaaS
aesthetic", "do not build a dashboard") does not match what is already there:
the current UI follows the brief's own **colour-as-meaning**, restrained
technical design language. The real work is **not** a wholesale rewrite of the
backend or a design wipe-out; it is closing the specific feature gaps in
section 63's priority order and extending the mental model.

## 2. Stack (verified)

| Layer        | Technology                                        | Verified |
|--------------|---------------------------------------------------|----------|
| Frontend     | React 19 + TypeScript + Vite 8 + Tailwind 4 + lucide + framer-motion + recharts | `npm run build` passes |
| Backend      | FastAPI + Pydantic v2 + uvicorn (Python 3.11 @ `backend/venv`) | tests pass |
| Simulation   | Python + NetworkX + NumPy (graph + agent engine)    | 13 engine tests pass |
| Vision       | `huggingface_hub` Inference API (DETR person count) | present, token-gated |
| Persistence  | SQLite (`backend/data/crowdflow.db`), seeded from `backend/data/*.json` | present |
| Testing      | pytest (backend)                                   | present |

## 3. Backend map

| Path | Role | Verdict |
|------|------|---------|
| `app/models.py` | Pydantic schemas: `VenueModel`, `ScenarioModel`, `SimulationState`, `ElementState`, `Bottleneck`, `Intervention`, `OptimizationResult` | **KEEP** (reusable contract) |
| `app/engine/venue.py` | NetworkX `VenueGraph` wrapper (types, capacities, connectivity) | **KEEP** |
| `app/engine/routing.py` | Congestion-aware `RoutingEngine` (A*, penalties, emergency discount) | **KEEP** |
| `app/engine/simulator.py` | `SimulationEngine`: spawn, movement, density, bottleneck, risk, interventions, clone/counterfactual, optimize | **KEEP** (core value) |
| `app/engine/predictor.py` | Linear-fit time-to-critical + trend + risk-level thresholds | **KEEP** |
| `app/engine/vision.py` | HF object-detection crowd counting | **KEEP** (already HF) |
| `app/storage.py` | SQLite venues/scenarios, seeding | **KEEP** |
| `app/routers/venues.py` `scenarios.py` | CRUD | **KEEP** |
| `app/routers/simulation.py` | run/step/play/pause/reset/speed/emergency/optimize/apply/counterfactual + WebSocket `/live` | **KEEP** |
| `app/routers/vision.py` | `/crowd-estimate` upload | **KEEP** |
| `app/main.py` | App wiring, CORS, health | **KEEP** (add routers) |

### Not present in backend (gaps)
- No **AI provider abstraction** (Groq ↔ Gemini) — no NL→scenario parsing, no
  explanation/suggestions endpoints. This is a *new* module.
- No **blueprint import** pipeline (OpenCV / Tesseract / PyMuPDF geometry
  extraction). Only crowd-counting exists.
- No **OSM / OpenRouteService** external-environment module.
- Scenario engine only models arrival / post-event exit-surge archetypes; no
  generic incident model (fire / weather / security / blocked / opened edges
  as first-class scenario inputs).
- No structured backend **observability** of AI calls (provider, latency,
  failures) — `vision.py` logs loosely, simulation has none.

> **Post-audit addendum (2026-08-11, Gap C/D/E closed):** the blueprint import
> pipeline (`app/blueprint/`, `POST /api/blueprint/import`) and the external
> environment module (`app/engine/environment.py`, `/api/environment`, external
> congestion in `SimulationState`) are now implemented, and the workspace has a
> 2.5D isometric venue canvas with venue/surround/network zoom levels. See the
> **Gap status** section in `README.md`. Items below marked "not present" for
> AI abstraction and observability remain open.

## 4. Frontend map

| Path | Role | Verdict |
|------|------|---------|
| `App.tsx` | Shell with mode rail (simulate/investigate/intervene/compare + venues/scenarios/settings) | **KEEP** but evolve |
| `store/SimulationContext.tsx` | Global state, WebSocket live feed, playback buffer, counterfactual feeds | **KEEP** (extend) |
| `lib/types.ts` | Mirrors backend schemas | **KEEP** (extend) |
| `lib/api.ts` | REST + `wsUrl` | **KEEP** (add AI/blueprint/etc.) |
| `lib/selection.ts` `format.ts` | node/edge selection, colour semantics | **KEEP** |
| `components/workspace/*` | `Instrument`, `InstrumentCanvas` (SVG venue), `Timeline`, `ContextPanel`, `TopBar`, `StatusBar`, `GuidedCard`, `EmptyState` | **KEEP** (canvas is the hero — evolve to 2.5D) |
| `views/*` | Venue/Scenario builders | **KEEP** (secondary) |
| `components/shell/*` | Rail, Settings | **KEEP** |

### Gaps in frontend
- Venue is rendered as a **flat top-down SVG**. The brief wants a
  sophisticated **2.5D / isometric** operational digital twin. This is the
  single biggest visual gap.
- No **natural-language command bar** wired to an AI scenario parser.
- No external **map** (OSM/MapLibre/Leaflet) surround layer with venue↔map
  zoom continuity.
- No blueprint **import/confirm** UI.
- Simulation still pushes **all agents** every tick (backend caps at 900
  agents in the packet, but no delta/typed-array path) — acceptable at ~1k
  but not 10k+.

## 5. What already works (verified)
- Deterministic simulation with seeded RNG; engine tests pass.
- Bottleneck detection with *real* signals (density, utilisation, queue,
  time-to-critical projection) — no invented "92% risk".
- Counterfactual `clone()` + `optimize()` run genuine second simulations and
  report real deltas.
- WebSocket live state; compare mode animates baseline vs counterfactual
  side-by-side with a synchronized readout.
- Guided first-run "bottleneck → what if → intervene" flow (wow moment #1 is
  largely present).

## 6. Build / run facts
- Backend: `backend/venv/Scripts/python -m uvicorn app.main:app --reload` (run
  from `backend/`). Env only optionally requires `HF_API_TOKEN`.
- Engine tests pass (13). Full suite is slow (~150s+ for engine, plus
  websocket suite) — not a build blocker.
- Frontend: `npm run dev` / `npm run build` (build passes).
- `VITE_API_BASE` defaults to `http://localhost:8000/api`.

## 7. Deployment assumptions
- Currently local-first (SQLite file + in-memory simulations + free HF).
- Target per brief: Vercel (React) + Render (FastAPI). SQLite is not
  appropriate for Render's ephemeral disk → demo data should remain seeded on
  boot; long-lived user data needs a real database. See REBUILD_PLAN.
