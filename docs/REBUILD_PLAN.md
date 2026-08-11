# CROWD FLOW — Rebuild Plan

Companion to `ARCHITECTURE_AUDIT.md`. The audit establishes that the backend is
a real simulation engine and the frontend is already an operational workspace —
so the plan is **surgical extension**, not a rewrite. Work is driven by the
brief's priority order (section 63) and the mental model (VENUE → TWIN →
ENVIRONMENT → CROWD → SCENARIO → SIMULATION → OBSERVE → RISK → INTERVENE →
COUNTERFACTUAL → COMPARE → RECOMMEND).

## CURRENT / KEEP / REWRITE / DELETE / ADD

### CURRENT (works today)
- FastAPI backend: `venues`, `scenarios`, `simulation` (run/step/play/pause/
  reset/speed/emergency/optimize/apply/counterfactual), `vision`, WebSocket.
- Simulation engine: agent spawning/movement, density, capacity, utilisation,
  risk, bottleneck forecast, congestion-aware routing, clone+optimize.
- SQLite storage seeded from `backend/data/*.json`.
- Frontend instrument workspace: venue SVG canvas, timeline scrubber, context
  inspector, compare mode, guided "what if" flow.
- HF crowd-counting via `huggingface_hub`.

### KEEP (reuse as-is)
- All of `backend/app/engine/*` (venue, routing, simulator, predictor).
- All `backend/app/models.py` schemas.
- All `backend/app/routers/*` and `storage.py`, `main.py`.
- `store/SimulationContext.tsx`, `lib/api.ts`, `lib/types.ts`,
  `lib/selection.ts`, `lib/format.ts`.
- `components/workspace/{Timeline,ContextPanel,TopBar,StatusBar,GuidedCard,EmptyState}`.
- Venue/scenario builders, shell rail/settings, theme tokens.

### REWRITE / EVOLVE (existing → better)
- `InstrumentCanvas.tsx` → 2.5D / isometric operational digital twin (the hero).
- Slim/strip any remaining pure-KPI surfaces; keep numbers contextual.
- Simulation WebSocket packet → support very large crowds (typed-array /
  delta / instanced rendering) rather than 900-object list.

### DELETE (dead / superseded)
- `frontend/src/assets/react.svg`, `vite.svg`, `App.css` (0-line), `hero.png`
  if unused. `stitch_crowdflow_ai/` is a design-still archive — not part of the
  runtime app; keep but do not ship assets from it.
- Any placeholder/mock KPI panels that do not map to real engine output
  (audit during each pass; none found so far — the app is already engine-driven).

### ADD (new capability — the actual rebuild)
1. **AI provider abstraction + NL scenario interface (Groq ↔ Gemini)** —
   `AIProvider` interface (`parseScenario`, `explainSimulation`,
   `generateScenarioSuggestions`) with `GroqProvider`/`GeminiProvider`, one
   configuration source, server-side secrets only, timeout/retry/429/validation,
   structured JSON out, validation before execution. Backend endpoint(s) +
   frontend "Ask what happens if…" command bar with an INTERPRETED SCENARIO →
   RUN SIMULATION confirmation.
2. **Generic incident / scenario engine** — fire, weather, security, blocked
   edge, opened edge, environmental modifiers as first-class scenario inputs
   (already partially supported via interventions; formalise the model).
3. **Blueprint import pipeline** — PNG/JPG/WEBP/PDF → normalize → geometry →
   line/wall detection → labels → semantic classification → venue graph →
   2.5D twin → user confirmation (OpenCV + Tesseract + PyMuPDF + HF only where
   it genuinely improves interpretation).
4. **External environment (OSM + OpenRouteService)** — surrounding roads /
   junctions / transit / parking; MapLibre or Leaflet map layer; venue↔map
   zoom continuity (Level 1/2/3); external congestion estimate; graceful
   fallback to bundled data when offline. Attribution: © OpenStreetMap.
5. **Optimization objectives** — extend `optimize` to support
   "minimize time subject to external congestion < threshold" etc.
6. **Observability** — structured backend logs for simulation + AI provider,
   latency, failures (no secrets).

## Phases (brief section 54), mapped to priority order

- **P0 AUDIT** — ✅ done (`docs/ARCHITECTURE_AUDIT.md`, this file).
- **P1–P6 core** — ✅ largely shipped: venue graph, moving crowd, bottleneck,
  interactive intervention, counterfactual, optimization. Gaps kept list below.
- **P7 BLUEPRINT** — new pipeline (heavy; needs local CV binaries).
- **P8 EXTERNAL MAP** — OSM + surrounding graph + external flow.
- **P9 AI** — provider abstraction + NL command bar (enables acceptance
  "ask naturally … receive a real simulation").
- **P10 DEPLOYMENT** — Vercel + Render.
- **P11 POLISH** — performance (instancing/typed arrays), responsive, loading,
  error handling, visual consistency.

Order of delivery this rebuild (value-per-effort, respects brief priority):
1. AI NL interface + provider abstraction (unlocks acceptance criteria, light,
   server-side).
2. Generic incident/weather/security scenario model.
3. 2.5D venue presentation (visual hero upgrade).
4. External OSM environment.
5. Blueprint import.
6. Deployment + observability + polish.

## Acceptance trace (section 60)
- "48,000 leaving; what happens" → existing simulate/observe flow (P1–6).
- "What happens if Gate B closes?" → **AI NL parser → scenario → simulation** (P9, this rebuild).
- "Fastest evacuation without road congestion" → optimizer with external
  congestion objective (P8 + P5).
- No fake numbers: every figure traces to engine metrics / deterministic calc /
  actual AI interpretation.

## Guardrails
- Deterministic engine only; LLM never simulates agents.
- Only server-side AI keys; validate all parsed JSON; graceful degradation
  (manual controls if AI/OSM/HF offline).
- Keep the backend simulation off Vercel serverless → Render.
