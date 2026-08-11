# CrowdFlow — Frontend

Operational command centre for predictive crowd safety & flow optimisation.

## Stack

- React 19 + TypeScript + Vite
- Tailwind CSS v4 (editorial-tech design system: Syne + JetBrains Mono, 1px grid lines, risk accent colors)
- Framer Motion + Lucide icons, Recharts for metric history
- Live video via WebSocket (`/api/simulation/{id}/live`)

## Run

```bash
npm install
npm run dev        # http://localhost:5173 (backend expected on :8000)
```

Point the frontend at a different API host with `VITE_API_BASE` (default `http://localhost:8000/api`).

## Checks

```bash
npm run build      # tsc -b && vite build
npm run lint       # oxlint
```

## Views

- **Dashboard** — crowd/risk/bottleneck overview with metric history charts
- **Simulation** — SVG venue map (agents, density, bottlenecks, suggested routes), PLAY / PAUSE / STEP / RESET / SPEED / EVACUATION controls, bottleneck watchlist, OPTIMIZE FLOW, Hugging Face crowd sensing
- **Optimisation** — ranked counterfactual interventions with real before/after deltas
- **Venue Architect** — interactive graph editor (nodes, walkways, capacities)
- **Scenario Builder** — crowd size, arrival/exit rates, distributions, event phases

## Data contract

`src/lib/types.ts` mirrors the backend Pydantic schemas; `src/lib/api.ts` is the typed client;
`src/store/SimulationContext.tsx` owns catalog + live simulation state.