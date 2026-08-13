# Implementation Plan: CrowdFlow Vertical Slice

## Overview

This plan implements the CrowdFlow vertical slice: a layered Canvas 2D crowd renderer, a
redesigned WHAT/WHY/IMPACT investigation panel, a full-width AI command bar, a spatial delta
comparison view, and an auto-loading demo venue. All changes are confined to the React frontend.
The backend, WebSocket protocol, Pydantic schemas, and `lib/types.ts` are immutable.

Tasks are ordered in seven waves so each wave's dependencies are completed before work begins
on the next wave. Wave 1 lays the foundation (no dependencies). Waves 2–6 build canvas layers,
panels, compare/delta view, and the command bar. Wave 7 adds unit and property-based tests.

## Tasks

- [x] 1. Extend SimulationContext with simRef, cfSimRef, WS throttle, and compareViewMode
  - Add `simRef` and `cfSimRef` as `React.RefObject<SimulationState | null>` inside `SimulationProvider`
  - Update WS `onmessage` to set `simRef.current` immediately on every frame (for rAF loop)
  - Add 100 ms throttle guard (`lastReactUpdateMs` ref) before calling `setSim` (max 10 React renders/s)
  - Define `CompareViewMode = 'baseline' | 'counterfactual' | 'delta'` type
  - Add `compareViewMode: CompareViewMode` and `setCompareViewMode` state to the provider
  - Expose all new fields in the context value object
  - Verify all existing consumers still type-check without modification
  - **Files**: `frontend/src/store/SimulationContext.tsx`
  - **Requirements**: Req 16, Req 17, Req 23

- [x] 2. Create utility modules delta.ts and quickActions.ts
  - Create `frontend/src/lib/delta.ts` with `DeltaEntry` interface (`id`, `kind`, `densityDelta`, `flowDelta`, `utilDelta`, `riskChanged`)
  - Implement `computeDelta(base, cf): DeltaEntry[]` — iterate edges then nodes, include only keys present in both states, compute signed differences (`cf value - base value`)
  - Implement `deltaColor(densityDelta, flowDelta): string` — green for density < -0.05, red for density > +0.05, blue for `|flowDelta| > 10`, `var(--od-line)` otherwise; always returns non-empty string
  - Create `frontend/src/lib/quickActions.ts` with `QuickAction` interface (`label`, `description`, `intervention: Omit<Intervention, 'id'>`, `variant: 'warn' | 'ok' | 'ghost'`)
  - Implement `quickActionsFor(bottleneck, venue, sim): QuickAction[]` — find up to two open alternate edges at source node as REDIRECT actions (`variant: 'ok'`); always append CLOSE_CORRIDOR fallback (`variant: 'warn'`)
  - Neither new type may be added to or modify `lib/types.ts`
  - **Files**: `frontend/src/lib/delta.ts`, `frontend/src/lib/quickActions.ts`
  - **Requirements**: Req 8, Req 10, Req 21, Req 22

- [x] 3. Create useCanvasSize ResizeObserver hook
  - Create `frontend/src/hooks/useCanvasSize.ts`
  - Implement `useCanvasSize(containerRef): { width: number; height: number }` with default `800 × 600`
  - Set up `ResizeObserver` on `containerRef.current` inside `useEffect`; call `setSize` with `e.contentRect.width` / `e.contentRect.height`
  - Return `ro.disconnect()` as the cleanup function
  - Export as named export; hook is shared by all Canvas 2D layers
  - **Files**: `frontend/src/hooks/useCanvasSize.ts`
  - **Requirements**: Req 1, Req 17

- [x] 4. Add CSS keyframe animations to App.css
  - Add `@keyframes bottleneck-pulse`: `0%: scale(0.8), opacity 0.9` → `100%: scale(2.2), opacity 0`
  - Add `.od-bottleneck-pulse`: `animation: bottleneck-pulse 1.4s ease-out infinite`, `transform-origin: center`, `transform-box: fill-box`
  - Add `.od-bottleneck-pulse-delay`: same as above with `animation-delay: 0.7s`
  - Add `@keyframes flow-dash`: `to { stroke-dashoffset: -24 }`
  - Add `.od-redirect-active`: `stroke-dasharray: 8 4`, `animation: flow-dash 0.6s linear infinite`
  - Add `@keyframes shimmer` and `.shimmer-line` helper class for AI loading state (gradient sweep over 1.2s)
  - Do not remove or alter any existing CSS rules
  - **Files**: `frontend/src/App.css`
  - **Requirements**: Req 5, Req 6, Req 13

- [x] 5. Create AutoLoadBridge component
  - Create `frontend/src/components/workspace/AutoLoadBridge.tsx`; component renders `null`
  - Declare `didAutoLoad = useRef(false)` idempotency guard; set to `true` before calling `selectVenue`
  - `useEffect` depends on `[s.venues, s.venue, s.scenarios]`; return early if `didAutoLoad.current`, `venues.length === 0`, or `venue !== null`
  - Prefer venue with `id === 'unity_arena'`; fall back to `venues[0]`
  - Call `s.selectScenario` for the default scenario (`sc.special?.default === true && sc.venue_id === demo.id`); fall back to any scenario for that venue
  - Must be a no-op when `venues.length === 0` (preserves `CreateTwinView` path)
  - **Files**: `frontend/src/components/workspace/AutoLoadBridge.tsx`
  - **Requirements**: Req 14, Req 20

- [x] 6. Create Canvas2DAgentLayer (InstrumentCanvasAgents.tsx)
  - Create `frontend/src/components/workspace/InstrumentCanvasAgents.tsx`
  - Accept props: `simRef`, `venue`, `showAgents`, `viewBoxX`, `viewBoxY`, `viewBoxW`, `viewBoxH`
  - On mount, attempt `canvas.getContext('2d')`; if null, set `canvasSupported = false`, log a warning, and return without starting the loop
  - Pre-allocate three `Float32Array` position buffers (normal: 4000×2, rerouted: 400×2, emergency: 200×2) — never allocate new arrays per frame
  - Start rAF loop: read `simRef.current`, compute `scaleX = canvasWidth / viewBoxW` / `scaleY = canvasHeight / viewBoxH`, partition agents by `is_emergency` / `is_rerouted`, fill buffers, then batch-draw each category with one `beginPath()` + `fill()` call
  - Coordinate transform: `canvasX = (venueX - viewBoxX) * scaleX`; `canvasY = (venueY - viewBoxY) * scaleY`
  - Skip draw and clear canvas when `showAgents === false`
  - Apply `pointer-events: none` on the `<canvas>` element; cancel rAF in `useEffect` cleanup
  - Target: 1,200 agents at ≥ 30fps in Chrome and Firefox
  - **Files**: `frontend/src/components/workspace/InstrumentCanvasAgents.tsx`
  - **Requirements**: Req 1, Req 2, Req 17, Req 19

- [x] 7. Create DensityGridLayer
  - Create `frontend/src/components/workspace/DensityGridLayer.tsx`
  - Render `<canvas>` absolutely positioned over venue SVG; only visible when `viewMode === 'density'` or `viewMode === 'crowd'`
  - Implement `computeDensityGrid(agents, venueW, venueH): Float32Array` — 20×20 grid (400 cells), accumulate `a.scale_units` (not agent count) into `col + row * 20` bin
  - Use `useEffect` watching `sim?.agents` (not a rAF loop); find `maxVal`, iterate all cells, skip cells with value < 0.5
  - Color: `hue = 120 - (val / maxVal) * 120`, `alpha = 0.06 + (val / maxVal) * 0.38`, fill with `hsla(hue, 75%, 48%, alpha)`
  - Full compute + draw cycle must complete in under 2ms for up to 1,200 agents
  - **Files**: `frontend/src/components/workspace/DensityGridLayer.tsx`
  - **Requirements**: Req 3, Req 17

- [x] 8. Create FlowArrowLayer
  - Create `frontend/src/components/workspace/FlowArrowLayer.tsx` — SVG layer for directional flow arrows
  - Only render arrows where `sim.edges[edgeKey].flow_per_min > 5`; skip edges at or below 5
  - Compute `magnitude = flow_per_min / edge.capacity`, clamped to [0, 1]
  - Arrow opacity = `0.4 + magnitude * 0.5`; color = `var(--od-warn)` when `magnitude > 0.7`, else `var(--od-soft)`
  - Render arrowhead SVG path at edge midpoint, rotated to source→destination direction
  - Implement frame counter throttle — render on every 3rd WebSocket frame only (~10fps at 30fps WS)
  - **Files**: `frontend/src/components/workspace/FlowArrowLayer.tsx`
  - **Requirements**: Req 4

- [x] 9. Create BottleneckPulseLayer
  - Create `frontend/src/components/workspace/BottleneckPulseLayer.tsx` — SVG layer for animated pulse rings
  - For each entry in `sim.bottlenecks`, compute midpoint coordinates for the bottleneck edge or node
  - Render two concentric `<circle>` rings per bottleneck: first with `className="od-bottleneck-pulse"`, second with `className="od-bottleneck-pulse-delay"` (0.7s phase offset defined in Task 4)
  - Ring fill: `var(--od-danger)` when `current_risk === 'CRITICAL'`, `var(--od-warn)` when `'HIGH'`
  - Render `"BOTTLENECK"` `<text>` badge above each midpoint
  - Return empty SVG (no rings) when `sim.bottlenecks.length === 0`; all animation is pure CSS keyframes
  - **Files**: `frontend/src/components/workspace/BottleneckPulseLayer.tsx`
  - **Requirements**: Req 5

- [x] 10. Refactor InstrumentCanvas — extract SVGVenueLayer and integrate all layers
  - Extract static venue geometry (edges, nodes, labels, iso floor/walls) into an `SVGVenueLayer` sub-component; re-renders only when `venue` prop or edge/node risk coloring changes
  - Remove all agent `<circle>` SVG elements from the SVG layer
  - Add `canvasSupported` state (default `true`); when Canvas2DAgentLayer signals unavailability, render fallback SVG agent circles in `SVGVenueLayer`
  - Wrap all layers in `CanvasStack` `<div style={{ position: 'relative' }}>` with `position: absolute; inset: 0` on each child
  - Z-order: SVGVenueLayer (Z-0), DensityGridLayer (Z-1), Canvas2DAgentLayer (Z-2, `pointer-events: none`), FlowArrowLayer (Z-3), BottleneckPulseLayer (Z-4), existing intervention/emergency overlays (Z-5, Z-6)
  - Apply `od-redirect-active` CSS class to active REDIRECT intervention lines in SVGVenueLayer
  - Apply framer-motion `initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }}` on newly-opened OPEN_CORRIDOR corridor lines
  - Pass `simRef` from context to `Canvas2DAgentLayer`
  - **Files**: `frontend/src/components/workspace/InstrumentCanvas.tsx`
  - **Requirements**: Req 1, Req 6, Req 19, Req 24

- [x] 11. Create BottleneckInvestigationPanel
  - Create `frontend/src/components/workspace/BottleneckInvestigationPanel.tsx`
  - Props: `bottleneck`, `elementState`, `venueElement`, `sim`, `venue`, `onDraftIntervention`, `onExplainAi`, `aiExplanation`, `aiBusy`, `aiConfigured`
  - WHAT block: location label, risk badge, density (agents/m²), flow per minute, queue count, utilisation %, progress bar with width `utilisation * 100`% colored green (NORMAL) / amber (ELEVATED or HIGH) / red (CRITICAL), time-to-critical countdown
  - WHY block: implement `routeConcentration(sim, edgeId): number` — count agents with consecutive source→destination pair in `route` array, divide by `sim.agents.length` (return 0 if empty); display percentage, demand vs capacity gap, `bottleneck.explanation`
  - IMPACT block: implement `cascadeEdges(bottleneck, venue, sim)` — connected edges at source/destination nodes filtered to non-NORMAL risk; display time-to-critical and cascade list
  - Quick actions: call `quickActionsFor` from Task 2; render each as full-width bordered button with `description` below `label`; on click call `onDraftIntervention` immediately (no mode navigation)
  - AI explain button: `"🧠 AI: What can I do?"`; disabled with tooltip `"Configure AI in Settings"` when `aiConfigured === false`; on click call `onExplainAi`
  - Show shimmer while `aiBusy === true`; render provider, summary, cause, and try_action chips when `aiExplanation` is available; chips call `onDraftIntervention({ id: crypto.randomUUID(), ...action })`
  - **Files**: `frontend/src/components/workspace/BottleneckInvestigationPanel.tsx`
  - **Requirements**: Req 9, Req 10, Req 11, Req 18

- [x] 12. Update ContextPanel — wire BottleneckInvestigationPanel and extend CompareReadout
  - Compute `isBottleneckSelected = !!(selected && sim?.bottlenecks.some(b => b.location === selected.id))`
  - Render `BottleneckInvestigationPanel` when `isBottleneckSelected === true`; render `ObjectDetail` when `false`; states are mutually exclusive (no mode tab required)
  - Extend CompareReadout with eight animated metric rows: in-venue count, average travel time, max utilisation, queue total, bottleneck count, clearance time, average stress (new), flow per minute (new)
  - Each delta value uses `motion.span` with `initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }}` and `transition={{ delay: rowIndex * 0.05 }}`
  - Negative deltas → `text-od-ok`; positive deltas → `text-od-danger`
  - Add "Did this help?" AI verdict card below metric table; clicking calls `api.aiExplain(cfSimId)` and renders response inline with APPLY INTERVENTION and DISCARD buttons
  - **Files**: `frontend/src/components/workspace/ContextPanel.tsx`
  - **Requirements**: Req 7, Req 9, Req 11

- [x] 13. Create DeltaInstrumentCanvas
  - Create `frontend/src/components/workspace/DeltaInstrumentCanvas.tsx`
  - Props: `baseSim: SimulationState`, `cfSim: SimulationState`, `venue: VenueModel`
  - Rendering pipeline: (1) draw all venue edges in muted style — `var(--od-line)` at 30% opacity; (2) call `computeDelta(baseSim, cfSim)`; (3) for each `DeltaEntry` with `|densityDelta| > 0.03`, draw thicker colored line (edge) or colored circle (node) using `deltaColor(densityDelta, flowDelta)`, opacity proportional to magnitude; (4) render bottom-left legend: three swatches labeled "Density decreased" (green), "Density increased" (red), "Flow redistributed" (blue)
  - Delta canvas shares the same SVG `viewBox` as the baseline canvas for spatial alignment
  - **Files**: `frontend/src/components/workspace/DeltaInstrumentCanvas.tsx`
  - **Requirements**: Req 7, Req 8, Req 21

- [x] 14. Update Instrument.tsx — compare mode layout and toggle strip
  - Add `CompareViewMode` toggle strip (`[BASELINE]`, `[COUNTERFACTUAL]`, `[DELTA]` chips) shown when `cfSim !== null`; wire chips to `setCompareViewMode` from context
  - Left pane: always render baseline canvas
  - Right pane: render counterfactual canvas when `compareViewMode === 'counterfactual'`; render `DeltaInstrumentCanvas` when `compareViewMode === 'delta'`
  - Reserve mounting slot between `TopBar` and workspace body for `CommandBarBanner` (Task 15)
  - Layout degrades correctly to single-pane when `cfSim === null`
  - **Files**: `frontend/src/components/workspace/Instrument.tsx`
  - **Requirements**: Req 7, Req 12

- [x] 15. Create CommandBarBanner
  - Create `frontend/src/components/workspace/CommandBarBanner.tsx` — full-width AI command bar replacing the `CommandBar` dropdown
  - Collapsed state (default, `h-8`): `"Ask CrowdFlow..."` prompt text + provider status dot; when sim has bottlenecks show ghost-text `"Explain the bottleneck at {sim.bottlenecks[0].location}"`; clicking anywhere expands
  - Expanded state: framer-motion `AnimatePresence` + `motion.div` with `initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.18, ease: 'easeOut' }}`
  - Expanded content: text input, INTERPRET button (disabled while `interpreting === true` — no-op on duplicate click), close button, up to 4 suggested prompt chips from `suggestedPrompts(sim, aiIdeas)`
  - `suggestedPrompts`: push bottleneck-location mention when non-empty; push sim-status–based prompts; append `aiIdeas` titles; slice to 4; clicking a chip fills input and calls `interpret()` immediately
  - AI response cards: render `AiInterpretResponse` card (confidence %, provider, delta fact chips, reasoning, RUN THIS VARIANT + run raw buttons); render `AiExplainResponse` explanation card (summary, cause, try_action chips)
  - Shimmer loading state (three lines, CSS gradient) while `aiBusy === true`
  - `aiError` non-null: display error in `var(--od-danger)` within response area; input remains enabled
  - `aiConfigured === false`: disable input with placeholder `"AI not configured — check Settings"`
  - `cfSim !== null`: show persistent `"Did this improve the situation?"` chip; clicking calls `api.aiExplain(cfSimId)`
  - **Files**: `frontend/src/components/workspace/CommandBarBanner.tsx`
  - **Requirements**: Req 12, Req 13, Req 18

- [x] 16. Mount AutoLoadBridge in App.tsx and update CreateTwinView gate
  - Import `AutoLoadBridge` in `App.tsx`
  - Mount `<AutoLoadBridge />` inside `<SimulationProvider>` before `<Shell />`
  - The `venue ? <Instrument> : <CreateTwinView>` gate naturally transitions once `AutoLoadBridge` sets the venue
  - Verify `CreateTwinView` is still shown when `venues.length === 0` (no regression)
  - **Files**: `frontend/src/App.tsx`
  - **Requirements**: Req 14, Req 15, Req 20

- [x] 17. Mount CommandBarBanner in Instrument.tsx and wire compare toggle
  - Import and mount `<CommandBarBanner />` between `TopBar` and the workspace body
  - Remove `CommandBar` from any existing mounting point in `Instrument.tsx`
  - Render `CompareViewMode` toggle strip when `cfSim !== null`; wire chips to `setCompareViewMode` from context
  - Switch right pane to `DeltaInstrumentCanvas` when `compareViewMode === 'delta'`
  - **Files**: `frontend/src/components/workspace/Instrument.tsx`
  - **Requirements**: Req 7, Req 12

- [x] 18. Redesign EmptyState overlay
  - When `venue !== null && sim === null`, render `EmptyState` as full-screen `position: absolute; inset: 0` overlay over the venue canvas
  - Apply `backdrop-filter: blur(2px)` and `background: rgba(var(--od-canvas-rgb), 0.55)` so venue geometry is visible through the overlay
  - Display: venue name, scenario name, large SIMULATE button (`h-14 px-10 text-base font-bold`), selected scenario crowd size
  - SIMULATE button calls `runSimulation()`; overlay is hidden when `sim !== null`
  - When `venues.length === 0`, EmptyState import button links to the Venues screen
  - **Files**: `frontend/src/components/workspace/Instrument.tsx`
  - **Requirements**: Req 15, Req 20

- [x] 19. Remove CommandBar from TopBar.tsx
  - Remove `import CommandBar` from `TopBar.tsx`
  - Remove the `<CommandBar />` render from `TopBar`
  - Verify no TypeScript errors or dead imports remain
  - Confirm no other TopBar functionality (venue name, scenario selector, play/pause) is affected
  - **Files**: `frontend/src/components/layout/TopBar.tsx`
  - **Requirements**: Req 12, Req 24

- [-] 20. Unit and property tests for delta.ts and quickActions.ts
  - Create `frontend/src/lib/__tests__/delta.test.ts`
  - Test `computeDelta`: correct `densityDelta` / `flowDelta` for known fixtures; keys absent from one state are skipped
  - Test anti-symmetry: `computeDelta(base, cf)[i].densityDelta === -computeDelta(cf, base)[i].densityDelta` for all matching entries
  - Property test (fast-check): `deltaColor(densityDelta, flowDelta)` always returns a non-empty string for any `float(-1,1)` × `float(-200,200)` input
  - Create `frontend/src/lib/__tests__/quickActions.test.ts`
  - Test `quickActionsFor`: at least one action always returned; CLOSE_CORRIDOR always present; REDIRECT actions added when alternates exist; `CLOSE_CORRIDOR` variant is `'warn'`; `REDIRECT` variant is `'ok'`
  - **Files**: `frontend/src/lib/__tests__/delta.test.ts`, `frontend/src/lib/__tests__/quickActions.test.ts`
  - **Requirements**: Req 8, Req 21, Req 22, Req 25

- [ ] 21. Unit tests for AutoLoadBridge, BottleneckInvestigationPanel trigger, and Canvas fallback
  - Create `frontend/src/components/workspace/__tests__/AutoLoadBridge.test.tsx`
  - Verify `selectVenue` called exactly once per mount (idempotency); `unity_arena` preferred, `venues[0]` fallback; no call when `venues.length === 0` or `venue !== null`; `selectScenario` called for default scenario
  - Create `frontend/src/components/workspace/__tests__/BottleneckInvestigationPanel.test.tsx`
  - Render `ContextPanel` with bottleneck-matching `selected` — verify `BottleneckInvestigationPanel` renders
  - Render `ContextPanel` with non-bottleneck `selected` — verify `ObjectDetail` renders, not `BottleneckInvestigationPanel` (mutual exclusivity)
  - Create `frontend/src/components/workspace/__tests__/InstrumentCanvasAgents.test.tsx`
  - Mock `HTMLCanvasElement.getContext` to return `null`; verify `canvasSupported` becomes `false` and no uncaught exception is thrown
  - **Files**: `frontend/src/components/workspace/__tests__/AutoLoadBridge.test.tsx`, `frontend/src/components/workspace/__tests__/BottleneckInvestigationPanel.test.tsx`, `frontend/src/components/workspace/__tests__/InstrumentCanvasAgents.test.tsx`
  - **Requirements**: Req 14, Req 9, Req 19, Req 25

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "name": "Foundation",
      "tasks": [1, 2, 3, 4, 5],
      "dependencies": []
    },
    {
      "wave": 2,
      "name": "Canvas Layers",
      "tasks": [6, 7, 8, 9, 10],
      "dependencies": [1, 2, 3, 4]
    },
    {
      "wave": 3,
      "name": "Investigation Panel",
      "tasks": [11, 12],
      "dependencies": [1, 2, 10]
    },
    {
      "wave": 4,
      "name": "Compare and Delta View",
      "tasks": [13, 14],
      "dependencies": [1, 2, 10, 11, 12]
    },
    {
      "wave": 5,
      "name": "Command Bar",
      "tasks": [15],
      "dependencies": [1, 4]
    },
    {
      "wave": 6,
      "name": "Integration and Wiring",
      "tasks": [16, 17, 18, 19],
      "dependencies": [5, 14, 15]
    },
    {
      "wave": 7,
      "name": "Tests",
      "tasks": [20, 21],
      "dependencies": [2, 5, 6, 11]
    }
  ],
  "taskDependencies": {
    "1": [],
    "2": [],
    "3": [],
    "4": [],
    "5": [],
    "6": [1, 3],
    "7": [1, 3],
    "8": [1, 3],
    "9": [4],
    "10": [6, 7, 8, 9],
    "11": [1, 2],
    "12": [10, 11],
    "13": [1, 2, 10],
    "14": [1, 12, 13],
    "15": [1, 4],
    "16": [5, 14],
    "17": [14, 15],
    "18": [5, 16],
    "19": [15, 17],
    "20": [2],
    "21": [5, 11, 6]
  }
}
```

## Notes

- **Immutable artefacts**: the backend engine, WebSocket protocol, Pydantic schemas in `backend/app/models.py`, and `frontend/src/lib/types.ts` must not be changed (Req 23).
- **No new npm packages**: all capabilities use browser APIs, `framer-motion`, and existing project dependencies (Req 23).
- **`DeltaEntry` and `QuickAction`** are defined in new local files (`lib/delta.ts`, `lib/quickActions.ts`) and must not be added to `lib/types.ts` (Req 21, Req 22).
- **`SimulationContextValue` extensions** must be additive only — no existing fields may be removed or renamed (Req 16, Req 23).
- **Property-based tests** use `fast-check` as the test library (Req 25).
- **Performance targets**: Canvas2DAgentLayer ≥ 30fps for 1,200 agents; DensityGridLayer < 2ms per cycle; `computeDelta` < 5ms for up to 200 edges+nodes (Req 17).
