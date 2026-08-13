# Requirements Document

## Introduction

CrowdFlow Vertical Slice upgrades an existing operational crowd-simulation dashboard into an
AI-native venue digital twin. The scope is limited to the React frontend: new canvas rendering
layers, a redesigned investigation panel, a full-width AI command bar, a spatial delta comparison
view, and an auto-loading demo venue. The backend simulation engine, WebSocket protocol, Pydantic
schemas, and `lib/types.ts` TypeScript contracts are treated as **immutable** — no change to any
of those artefacts is permitted by this spec.

---

## Glossary

- **Agent**: A simulated crowd member represented by an `AgentModel` object from `lib/types.ts`.
- **AgentLayer**: The `Canvas2DAgentLayer` component that renders agent positions using a Canvas 2D
  `requestAnimationFrame` loop.
- **AutoLoadBridge**: A React component that automatically selects the demo venue on first mount.
- **Baseline**: The primary running simulation (`simId` / `sim` in `SimulationContext`).
- **BottleneckInvestigationPanel**: The WHAT/WHY/IMPACT panel rendered in `ContextPanel` when a
  bottleneck element is selected.
- **CanvasStack**: The `<div>` container with `position: relative` that holds all six rendering layers.
- **CF / Counterfactual**: A forked simulation (`cfSimId` / `cfSim`) that runs an intervention
  scenario in parallel with the baseline.
- **CommandBarBanner**: The full-width AI command bar mounted between `TopBar` and the workspace body.
- **CompareViewMode**: The three-state toggle — `'baseline'`, `'counterfactual'`, or `'delta'` —
  controlling which view is shown in the right pane of compare mode.
- **DeltaEntry**: A local data type (`frontend/src/lib/delta.ts`) describing the signed difference
  in density, flow, and utilisation between baseline and counterfactual for one edge or node.
- **DensityGridLayer**: A Canvas 2D element that overlays a 20×20 spatial bin heatmap.
- **QuickAction**: A local data type (`frontend/src/lib/quickActions.ts`) describing a one-click
  intervention button with a label, description, and pre-built `Intervention` payload.
- **rAF Loop**: A `requestAnimationFrame` render loop that reads from `simRef.current` and draws
  to a Canvas 2D context without triggering React reconciliation.
- **simRef**: A `React.RefObject<SimulationState | null>` exposed from `SimulationContext` and
  updated on every WebSocket frame — used by the rAF loop to avoid per-frame React renders.
- **SVGVenueLayer**: The static SVG element that renders venue geometry (edges, nodes, labels).
- **Unity Arena**: The seeded demo venue (`venue_id = 'unity_arena'`) used for the auto-load flow.
- **WS**: WebSocket — the live simulation data stream provided by the immutable backend.

---

## Requirements

---

### Requirement 1: Canvas Layer Architecture

**User Story:** As a demo operator, I want the venue canvas to render 1,200 simulated agents
smoothly, so that stakeholders immediately see a live, high-fidelity crowd simulation.

#### Acceptance Criteria

1. THE CanvasStack SHALL render six layers in Z-order: SVGVenueLayer (Z-0), DensityGridLayer
   (Z-1), Canvas2DAgentLayer (Z-2), FlowArrowLayer (Z-3), BottleneckPulseLayer (Z-4), and
   intervention/emergency overlays (Z-5 and Z-6).
2. WHEN the CanvasStack mounts, THE SVGVenueLayer SHALL use `position: absolute; inset: 0` and
   all Canvas 2D layers SHALL be sized to match the SVGVenueLayer's rendered pixel dimensions
   via a `ResizeObserver`.
3. THE SVGVenueLayer SHALL render venue geometry (edges, nodes, labels) and SHALL re-render only
   when the `venue` prop changes or edge/node risk coloring changes.
4. THE SVGVenueLayer SHALL NOT render agent `<circle>` elements.
5. WHEN the viewport is resized, THE CanvasStack SHALL update all Canvas 2D layer
   `width` and `height` attributes to match the new container pixel dimensions within one
   `ResizeObserver` callback.
6. THE Canvas2DAgentLayer SHALL set `pointer-events: none` so that SVG hit testing is
   unaffected.
7. THE Canvas2DAgentLayer SHALL expose a `canvasSupported` flag; IF the Canvas 2D context
   fails to initialize, THEN THE SVGVenueLayer SHALL render a fallback SVG agent layer.

---

### Requirement 2: Canvas 2D Agent Renderer

**User Story:** As a demo operator, I want agent dots to animate fluidly at 30fps, so that the
simulation looks alive and impressive without browser-tab lag.

#### Acceptance Criteria

1. THE Canvas2DAgentLayer SHALL use a `requestAnimationFrame` loop that reads agent positions
   from `simRef.current` and does not call `setState` per frame.
2. WHEN the rAF loop executes, THE Canvas2DAgentLayer SHALL draw exactly one `ctx.arc()` call
   per agent in `simRef.current.agents` — no agent is skipped and no agent is drawn twice.
3. THE Canvas2DAgentLayer SHALL partition agents into three categories — normal, rerouted
   (`is_rerouted === true`), and emergency (`is_emergency === true`) — and batch-draw each
   category in a single `ctx.beginPath()` / `ctx.fill()` call.
4. THE Canvas2DAgentLayer SHALL use pre-allocated `Float32Array` buffers (one per category)
   and SHALL NOT allocate new arrays per frame.
5. WHEN `showAgents` prop is `false`, THE Canvas2DAgentLayer SHALL skip drawing and clear
   the canvas.
6. THE Canvas2DAgentLayer coordinate transform SHALL map venue coordinates to canvas pixels
   using the formula: `canvasX = (venueX - viewBoxX) * (canvasWidth / viewBoxW)` and
   `canvasY = (venueY - viewBoxY) * (canvasHeight / viewBoxH)`.
7. THE Canvas2DAgentLayer SHALL render with a target of 1,200 agents at ≥ 30fps in a
   modern browser (Chrome or Firefox).

---

### Requirement 3: Density Grid Heatmap

**User Story:** As a safety analyst, I want a live density heatmap overlay, so that I can
instantly identify where crowd concentration is building.

#### Acceptance Criteria

1. WHEN `viewMode === 'density'` OR `viewMode === 'crowd'`, THE DensityGridLayer SHALL be
   visible; in all other view modes it SHALL be hidden.
2. THE DensityGridLayer SHALL compute a 20×20 spatial bin grid from `sim.agents` positions,
   accumulating `scale_units` (not raw agent count) per bin.
3. THE DensityGridLayer SHALL update at the WebSocket frame rate using a `useEffect` that
   watches `sim.agents` — it SHALL NOT use a `requestAnimationFrame` loop.
4. FOR ALL valid agent arrays within venue bounds, the sum of all density grid cell values
   SHALL equal the sum of `scale_units` across all agents (conservation invariant).
5. WHEN a grid cell value is less than 0.5, THE DensityGridLayer SHALL skip drawing that
   cell (no visible fill).
6. THE DensityGridLayer SHALL color cells using `hsla(hue, 75%, 48%, alpha)` where
   `hue = 120 - (cellDensity / maxDensity) * 120` (green at zero → red at maximum) and
   `alpha = 0.06 + (cellDensity / maxDensity) * 0.38`.
7. THE DensityGridLayer SHALL complete the grid compute-and-draw cycle in under 2ms for
   up to 1,200 agents.

---

### Requirement 4: Flow Arrow Layer

**User Story:** As a safety analyst, I want directional flow arrows on corridors, so that I can
see where crowd movement is concentrating and in which direction.

#### Acceptance Criteria

1. WHEN `sim.edges[edgeKey].flow_per_min > 5`, THE FlowArrowLayer SHALL render a directional
   arrow at the midpoint of that edge.
2. THE FlowArrowLayer SHALL NOT render arrows on edges where `flow_per_min ≤ 5`.
3. THE FlowArrowLayer arrow opacity SHALL be `0.4 + magnitude * 0.5` where
   `magnitude = flow_per_min / edge.capacity`, clamped to [0, 1].
4. WHEN `magnitude > 0.7`, THE FlowArrowLayer SHALL color the arrow with `var(--od-warn)`;
   otherwise it SHALL use `var(--od-soft)`.
5. THE FlowArrowLayer SHALL update at the WebSocket frame rate, throttled to every 3rd frame
   (approximately 10fps when the WS stream runs at 30fps).

---

### Requirement 5: Bottleneck Pulse Animation

**User Story:** As a safety analyst, I want bottleneck locations to visually pulse on the canvas,
so that I can identify at a glance where the simulation engine has detected dangerous congestion.

#### Acceptance Criteria

1. WHEN `sim.bottlenecks` is non-empty, THE BottleneckPulseLayer SHALL render pulsing rings at
   the midpoint of each bottleneck edge or node.
2. THE BottleneckPulseLayer SHALL render exactly two concentric SVG circle rings per bottleneck,
   with the second ring offset by 0.7 seconds via the `od-bottleneck-pulse-delay` CSS class.
3. THE BottleneckPulseLayer ring color SHALL be `var(--od-danger)` when
   `bottleneck.current_risk === 'CRITICAL'` and `var(--od-warn)` when
   `bottleneck.current_risk === 'HIGH'`.
4. THE BottleneckPulseLayer SHALL render a text badge labeled "BOTTLENECK" above the pulse
   ring midpoint.
5. THE BottleneckPulseLayer pulse animation SHALL use a CSS `@keyframes` rule
   (`bottleneck-pulse`) defined in `App.css` — no JavaScript animation is used.
6. WHEN `sim.bottlenecks` becomes empty, THE BottleneckPulseLayer SHALL render no rings.

---

### Requirement 6: Intervention Effect Animations

**User Story:** As an operator, I want visual feedback on the canvas when interventions are
applied, so that I can confirm that my action has taken effect.

#### Acceptance Criteria

1. WHEN an `OPEN_CORRIDOR` intervention is applied, THE SVGVenueLayer SHALL play a
   framer-motion expand animation (`initial={{ opacity: 0, scale: 0.6 }} → animate={{ opacity: 1,
   scale: 1 }}`) on the newly-opened corridor line.
2. WHEN a `REDIRECT` intervention is active in `sim.interventions_applied`, THE SVGVenueLayer
   SHALL apply the `od-redirect-active` CSS class to the corresponding dashed line, producing a
   flowing `stroke-dashoffset` animation.
3. THE `od-redirect-active` CSS animation SHALL use `stroke-dasharray: 8 4` and animate
   `stroke-dashoffset` to `-24` with duration `0.6s linear infinite`.

---

### Requirement 7: Compare / Delta View

**User Story:** As a safety analyst, I want to compare a baseline simulation against a
counterfactual side-by-side and see a spatial delta view, so that I can quantify whether an
intervention improved crowd safety.

#### Acceptance Criteria

1. WHEN `cfSim !== null`, THE Instrument SHALL render a compare layout with a `CompareViewMode`
   toggle strip showing `[BASELINE]`, `[COUNTERFACTUAL]`, and `[DELTA]` options.
2. THE compare layout left pane SHALL always display the baseline canvas.
3. WHEN `compareMode === 'counterfactual'`, THE right pane SHALL display the counterfactual
   simulation canvas.
4. WHEN `compareMode === 'delta'`, THE right pane SHALL display `DeltaInstrumentCanvas`.
5. THE `DeltaInstrumentCanvas` SHALL render venue geometry in muted style (`var(--od-line)` at
   30% opacity) and overlay `DeltaEntry` colors on edges and nodes with
   `|densityDelta| > 0.03`.
6. THE `DeltaInstrumentCanvas` SHALL color delta overlays as follows:
   `densityDelta < -0.05` → `hsl(142, 70%, 45%)` (improvement);
   `densityDelta > +0.05` → `hsl(0, 70%, 50%)` (worsening);
   `|densityDelta| ≤ 0.05 AND |flowDelta| > threshold` → `hsl(210, 70%, 55%)` (redistribution).
7. THE `DeltaInstrumentCanvas` SHALL render a legend in the bottom-left corner with labels for
   density decreased, density increased, and flow redistributed.
8. THE `CompareReadout` panel SHALL display animated metric deltas for: in-venue count, average
   travel time, max utilisation, queue total, bottleneck count, clearance time, average stress,
   and flow per minute.
9. WHEN the delta value is negative (improvement), THE CompareReadout SHALL render the delta
   value in `text-od-ok` color; when positive (worsening), in `text-od-danger` color.

---

### Requirement 8: Delta Computation

**User Story:** As a developer, I want a pure `computeDelta` function, so that the spatial delta
view is always consistent and testable.

#### Acceptance Criteria

1. THE `computeDelta` function SHALL accept two `SimulationState` objects and return a
   `DeltaEntry[]` containing one entry per edge or node key present in **both** simulation
   states.
2. WHEN an edge or node key exists in only one of the two simulation states, THE `computeDelta`
   function SHALL omit that key from the result.
3. FOR ALL pairs of valid `SimulationState` objects, `computeDelta(base, cf)[i].densityDelta`
   SHALL equal `-computeDelta(cf, base)[i].densityDelta` for every corresponding entry
   (anti-symmetry / delta symmetry property).
4. THE `DeltaEntry` type SHALL include: `id: string`, `kind: 'edge' | 'node'`,
   `densityDelta: number`, `flowDelta: number`, `utilDelta: number`, `riskChanged: boolean`.
5. THE `computeDelta` function SHALL complete in under 5ms for a venue with up to 200 edges
   and nodes combined.

---

### Requirement 9: Investigation Panel — WHAT/WHY/IMPACT

**User Story:** As a safety analyst, I want to click on a bottleneck corridor and immediately
see a structured explanation of what is happening, why it is happening, and what the cascading
impact is, so that I can make an informed intervention decision.

#### Acceptance Criteria

1. WHEN `selected` is non-null AND `sim.bottlenecks.some(b => b.location === selected.id)` is
   true, THE ContextPanel SHALL render `BottleneckInvestigationPanel` instead of the generic
   `ObjectDetail` component.
2. WHEN `isBottleneckSelected` is false, THE ContextPanel SHALL render `ObjectDetail`.
   These two states SHALL be mutually exclusive.
3. THE `BottleneckInvestigationPanel` WHAT block SHALL display: location label, risk badge,
   density (agents/m²), flow per minute, queue count, utilisation percentage, utilisation
   progress bar, and time-to-critical countdown.
4. THE `BottleneckInvestigationPanel` utilisation progress bar width SHALL equal
   `utilisation * 100`% and SHALL be colored green when risk is NORMAL, amber for ELEVATED
   or HIGH, and red for CRITICAL.
5. THE `BottleneckInvestigationPanel` WHY block SHALL display the route concentration
   percentage computed by `routeConcentration(sim, edgeId)`, the demand vs. capacity gap,
   and `bottleneck.explanation`.
6. THE `routeConcentration` function SHALL return the fraction of `sim.agents` whose `route`
   array contains the edge (consecutive source→destination node pair), returning 0 when
   `sim.agents` is empty.
7. THE `BottleneckInvestigationPanel` IMPACT block SHALL display time-to-critical and the
   list of connected edges with non-NORMAL risk levels from `cascadeEdges()`.
8. WHEN the investigation panel is rendered without navigating to the Intervene mode tab,
   THE ContextPanel SHALL show the full WHAT/WHY/IMPACT view — mode tab selection SHALL NOT
   be required to trigger the investigation panel.

---

### Requirement 10: Quick-Action Buttons

**User Story:** As an operator, I want one-click intervention buttons in the investigation panel,
so that I can apply a recommended intervention without switching mode tabs.

#### Acceptance Criteria

1. THE `quickActionsFor` function SHALL always return at least one `QuickAction` — the
   `CLOSE_CORRIDOR` action for the bottleneck edge SHALL always be appended as a fallback.
2. WHEN alternate open edges exist at the bottleneck source node, THE `quickActionsFor`
   function SHALL include up to two `REDIRECT` quick actions targeting those edges.
3. THE `QuickAction` type SHALL include: `label: string`, `description: string`,
   `intervention: Omit<Intervention, 'id'>`, and `variant: 'warn' | 'ok' | 'ghost'`.
4. WHEN a quick-action button is clicked, THE `BottleneckInvestigationPanel` SHALL call
   `onDraftIntervention` with the corresponding intervention — no mode navigation SHALL occur.
5. THE `CLOSE_CORRIDOR` quick-action variant SHALL be `'warn'`; `REDIRECT` quick-action
   variants SHALL be `'ok'`.
6. WHEN the quick-action buttons are rendered, THE BottleneckInvestigationPanel SHALL display
   each action as a full-width bordered button with the `description` text below the `label`.

---

### Requirement 11: AI Explain (Inline)

**User Story:** As a safety analyst, I want to ask the AI what I can do about a bottleneck and
see the answer inline in the investigation panel, so that I get actionable guidance without
leaving my current context.

#### Acceptance Criteria

1. THE `BottleneckInvestigationPanel` SHALL render an "🧠 AI: What can I do?" button below the
   quick-action buttons.
2. WHEN the AI explain button is clicked, THE BottleneckInvestigationPanel SHALL call
   `explainCurrent()` from `SimulationContext`.
3. WHILE `aiBusy` is `true`, THE BottleneckInvestigationPanel SHALL display a shimmer loading
   state in the AI response area.
4. WHEN `aiExplanation` is available, THE BottleneckInvestigationPanel SHALL render: provider
   name, summary text, cause text, and each `try_action` as a clickable chip.
5. WHEN a `try_action` chip is clicked, THE BottleneckInvestigationPanel SHALL construct an
   `Intervention` with `crypto.randomUUID()` id and call `onDraftIntervention`.
6. IF `aiConfigured` is `false`, THEN THE AI explain button SHALL be rendered as disabled with
   tooltip text "Configure AI in Settings".

---

### Requirement 12: AI Command Bar (CommandBarBanner)

**User Story:** As an operator, I want a persistent, prominent AI command bar at the top of the
workspace, so that natural-language simulation control is always one click away.

#### Acceptance Criteria

1. THE `CommandBarBanner` SHALL be rendered between `TopBar` and the workspace body in
   `Instrument.tsx` at full width.
2. THE `TopBar` SHALL NOT render the previous `CommandBar` dropdown component after this change.
3. THE `CommandBarBanner` default state SHALL be collapsed (`h-8`), showing the prompt text
   "Ask CrowdFlow..." and an AI provider status dot on the right.
4. WHEN the collapsed `CommandBarBanner` strip is clicked, THE CommandBarBanner SHALL expand
   using a framer-motion animation (`height: 0 → 'auto'`, `opacity: 0 → 1`, duration 0.18s).
5. WHEN `sim` is running and `sim.bottlenecks` is non-empty, THE collapsed CommandBarBanner
   SHALL display a ghost-text contextual suggestion referencing `sim.bottlenecks[0].location`.
6. THE expanded `CommandBarBanner` SHALL display: a text input, an INTERPRET button, a close
   button, and up to 4 suggested prompt chips.
7. WHEN the INTERPRET button is clicked while `interpreting` is already `true`, THE
   CommandBarBanner SHALL treat the action as a no-op (button is `disabled` during
   in-flight interpretation).
8. THE `suggestedPrompts` function SHALL return up to 4 prompts derived from the current
   simulation state, including bottleneck location mentions when `sim.bottlenecks` is non-empty.
9. WHEN a suggested prompt chip is clicked, THE CommandBarBanner SHALL fill the text input with
   that prompt and immediately call `interpret()`.

---

### Requirement 13: AI Response Cards

**User Story:** As an operator, I want the AI response shown as a structured card rather than
raw text, so that I can understand the interpretation at a glance and act on it immediately.

#### Acceptance Criteria

1. WHEN `preview` (`AiInterpretResponse`) is available, THE CommandBarBanner SHALL render a
   response card showing: confidence percentage, provider name, delta fact chips from
   `preview.delta`, reasoning text, a "RUN THIS VARIANT" button, and a "run raw" button.
2. WHEN `aiExplanation` (`AiExplainResponse`) is available, THE CommandBarBanner SHALL render
   an explanation card showing: provider name, summary, cause, and each `try_action` as a chip.
3. WHILE `aiBusy` is `true`, THE CommandBarBanner SHALL display a shimmer loading state
   (three lines of varying width with a CSS gradient animation) in place of the response card.
4. WHEN `cfSim !== null`, THE CommandBarBanner SHALL display a persistent suggestion chip
   "Did this improve the situation?" that calls `api.aiExplain(cfSimId)` when clicked.
5. IF `aiError` is non-null, THEN THE CommandBarBanner SHALL display the error message in
   `var(--od-danger)` style within the response area.

---

### Requirement 14: Demo Venue Auto-Load

**User Story:** As a demo operator, I want the demo venue to be displayed instantly on first
load without any user interaction, so that stakeholders are immediately impressed by the
visualization.

#### Acceptance Criteria

1. WHEN `SimulationProvider` mounts and `venues.length > 0` AND `venue === null`,
   THE `AutoLoadBridge` SHALL call `selectVenue('unity_arena')` if a venue with
   `id === 'unity_arena'` exists in the venues array; otherwise it SHALL select `venues[0]`.
2. THE `AutoLoadBridge` SHALL set `didAutoLoad.current = true` before calling `selectVenue`,
   ensuring `selectVenue` is called at most once per mount regardless of how many times the
   `useEffect` re-runs.
3. WHEN `venue` is already non-null, THE `AutoLoadBridge` SHALL not call `selectVenue`.
4. WHEN `venues.length === 0`, THE `AutoLoadBridge` SHALL not call `selectVenue` and the
   `CreateTwinView` SHALL be shown as before.
5. THE `AutoLoadBridge` SHALL be mounted inside `<SimulationProvider>` in `App.tsx` before
   `<Shell />`.
6. WHEN a default scenario (`special.default === true`) exists for the auto-loaded venue,
   THE `AutoLoadBridge` SHALL call `selectScenario` for that scenario.

---

### Requirement 15: Empty State Overlay

**User Story:** As a demo operator, I want a visually impactful play button rendered over the
venue SVG when no simulation is running, so that the venue is visible before simulation starts.

#### Acceptance Criteria

1. WHEN `venue !== null` AND `sim === null`, THE Instrument SHALL render the `EmptyState`
   overlay as a full-screen overlay on the canvas.
2. THE `EmptyState` overlay SHALL use `backdrop-filter: blur(2px)` and
   `background: rgba(var(--od-canvas-rgb), 0.55)` so the venue SVG geometry is visible through
   the overlay.
3. THE `EmptyState` overlay SHALL display: the venue name, the scenario name, a large SIMULATE
   button (`h-14 px-10 text-base font-bold`), and the selected scenario crowd size.
4. WHEN the SIMULATE button is clicked, THE `EmptyState` overlay SHALL call `runSimulation()`.
5. WHEN `sim !== null`, THE `EmptyState` overlay SHALL not be rendered.

---

### Requirement 16: SimulationContext — simRef and WS Throttle

**User Story:** As a developer, I want `SimulationContext` to expose `simRef` and throttle
React state updates to 10fps, so that the rAF loop has zero React overhead and UI panels
remain responsive without over-rendering.

#### Acceptance Criteria

1. THE `SimulationContext` SHALL expose `simRef: React.RefObject<SimulationState | null>` and
   `cfSimRef: React.RefObject<SimulationState | null>` as new context values.
2. WHEN a WebSocket message is received, THE `SimulationContext` SHALL update `simRef.current`
   immediately on every message.
3. WHEN a WebSocket message is received, THE `SimulationContext` SHALL call `setSim(state)` at
   most once per 100ms (throttled to 10 React renders per second).
4. THE `simRef.current` value SHALL always be equal to or more recent than the `sim` React state
   — `simRef.current` SHALL be set before or concurrently with `setSim`.
5. THE `SimulationContext` SHALL expose `compareViewMode: CompareViewMode` and
   `setCompareViewMode: (m: CompareViewMode) => void`.
6. THE `SimulationContextValue` interface extensions SHALL be backward-compatible — all existing
   consumers of the context SHALL continue to function without modification.

---

### Requirement 17: Performance Targets

**User Story:** As a demo operator, I want the simulation to run smoothly under load, so that
the demo is not interrupted by frame drops or UI freezes.

#### Acceptance Criteria

1. THE Canvas2DAgentLayer SHALL render up to 1,200 agents at a sustained ≥ 30fps frame rate
   in Chrome and Firefox on a modern laptop.
2. THE DensityGridLayer SHALL complete one compute-and-draw cycle in under 2ms measured with
   `performance.now()` for up to 1,200 agents.
3. THE `computeDelta` function SHALL complete in under 5ms for a venue with up to 200 combined
   edges and nodes.
4. WHILE compare mode is active with two simultaneous WebSocket streams, both
   Canvas2DAgentLayer instances SHALL maintain ≥ 20fps.
5. WHEN the viewport is resized, THE CanvasStack SHALL complete its resize response within one
   `ResizeObserver` callback cycle.
6. THE Canvas2DAgentLayer SHALL use pre-allocated `Float32Array` buffers and SHALL NOT trigger
   garbage collection per frame.

---

### Requirement 18: Error Handling — AI Unavailable

**User Story:** As an operator, I want the UI to remain functional when AI is not configured,
so that manual intervention workflows are never blocked by missing AI credentials.

#### Acceptance Criteria

1. WHEN `aiConfigured` is `false`, THE CommandBarBanner input SHALL be disabled with
   placeholder text "AI not configured — check Settings".
2. WHEN `aiConfigured` is `false`, THE "🧠 AI: What can I do?" button in
   `BottleneckInvestigationPanel` SHALL be rendered as disabled with a visible tooltip
   "Configure AI in Settings".
3. WHEN `aiConfigured` is `false`, THE quick-action buttons in `BottleneckInvestigationPanel`
   SHALL remain fully functional.
4. IF `aiError` is non-null, THEN THE CommandBarBanner SHALL display the error text within
   the response area in `var(--od-danger)` styling and the input SHALL remain enabled for
   a retry.

---

### Requirement 19: Error Handling — Canvas Fallback

**User Story:** As a developer, I want the application to remain usable if Canvas 2D is
unavailable, so that the tool works in environments with limited graphics support.

#### Acceptance Criteria

1. IF the Canvas 2D context fails to initialize (`getContext('2d')` returns null), THEN THE
   Canvas2DAgentLayer SHALL set `canvasSupported` to `false` and log a warning.
2. WHEN `canvasSupported` is `false`, THE SVGVenueLayer SHALL render fallback SVG `<circle>`
   elements for agents.
3. THE Canvas2DAgentLayer SHALL NOT throw an uncaught exception when the 2D context is
   unavailable.

---

### Requirement 20: Error Handling — Empty Venues

**User Story:** As a first-time user, I want the application to gracefully handle a backend with
no seeded venues, so that the experience degrades cleanly to the create-twin flow.

#### Acceptance Criteria

1. WHEN `venues.length === 0` after the catalog loads, THE `AutoLoadBridge` SHALL perform no
   action.
2. WHEN `venues.length === 0`, THE `App` SHALL display `CreateTwinView` as before this spec.
3. WHEN `venues.length === 0`, THE `EmptyState` overlay import button SHALL link to the Venues
   screen.

---

### Requirement 21: Data Contract — DeltaEntry

**User Story:** As a developer, I want `DeltaEntry` to be a well-typed, immutable contract in a
dedicated module, so that delta computation is decoupled from rendering concerns.

#### Acceptance Criteria

1. THE `DeltaEntry` interface SHALL be defined in `frontend/src/lib/delta.ts` and SHALL NOT
   be added to `lib/types.ts`.
2. THE `DeltaEntry` interface SHALL include all fields: `id: string`, `kind: 'edge' | 'node'`,
   `densityDelta: number`, `flowDelta: number`, `utilDelta: number`, `riskChanged: boolean`.
3. THE `computeDelta` function SHALL be exported from `frontend/src/lib/delta.ts`.
4. THE `deltaColor` function SHALL be exported from `frontend/src/lib/delta.ts` and SHALL
   accept `(densityDelta: number, flowDelta: number): string`.
5. FOR ALL valid numeric inputs to `deltaColor`, THE function SHALL return a non-empty string.

---

### Requirement 22: Data Contract — QuickAction

**User Story:** As a developer, I want `QuickAction` to be a typed contract in a dedicated
module, so that quick-action computation is independently testable.

#### Acceptance Criteria

1. THE `QuickAction` interface SHALL be defined in `frontend/src/lib/quickActions.ts` and
   SHALL NOT be added to `lib/types.ts`.
2. THE `QuickAction` interface SHALL include all fields: `label: string`, `description: string`,
   `intervention: Omit<Intervention, 'id'>`, `variant: 'warn' | 'ok' | 'ghost'`.
3. THE `quickActionsFor` function SHALL be exported from `frontend/src/lib/quickActions.ts`.

---

### Requirement 23: Codebase Constraints

**User Story:** As a developer, I want all changes confined to the React frontend, so that the
production backend and data contracts remain stable.

#### Acceptance Criteria

1. THE backend simulation engine files SHALL NOT be modified.
2. THE WebSocket protocol SHALL NOT be modified.
3. THE `frontend/src/lib/types.ts` file SHALL NOT be modified.
4. THE Pydantic schemas in `backend/app/models.py` SHALL NOT be modified.
5. THE new `DeltaEntry` and `QuickAction` types SHALL be defined in new local files, not
   in `lib/types.ts`.
6. THE `SimulationContextValue` extensions SHALL be added only by extending the existing
   interface, not by removing or renaming existing fields.
7. No new npm packages SHALL be introduced — all capabilities SHALL use browser APIs,
   `framer-motion`, and existing project dependencies.

---

### Requirement 24: New Component Files

**User Story:** As a developer, I want a clear file-level contract for all new components, so
that the implementation scope is unambiguous.

#### Acceptance Criteria

1. THE following new component files SHALL be created:
   - `frontend/src/components/workspace/InstrumentCanvasAgents.tsx`
   - `frontend/src/components/workspace/DensityGridLayer.tsx`
   - `frontend/src/components/workspace/FlowArrowLayer.tsx`
   - `frontend/src/components/workspace/BottleneckPulseLayer.tsx`
   - `frontend/src/components/workspace/BottleneckInvestigationPanel.tsx`
   - `frontend/src/components/workspace/CommandBarBanner.tsx`
   - `frontend/src/components/workspace/DeltaInstrumentCanvas.tsx`
   - `frontend/src/components/workspace/AutoLoadBridge.tsx`
   - `frontend/src/lib/delta.ts`
   - `frontend/src/lib/quickActions.ts`
   - `frontend/src/hooks/useCanvasSize.ts`
2. THE following existing files SHALL be modified (and only these):
   - `frontend/src/store/SimulationContext.tsx`
   - `frontend/src/components/workspace/InstrumentCanvas.tsx`
   - `frontend/src/components/workspace/Instrument.tsx`
   - `frontend/src/components/workspace/ContextPanel.tsx`
   - `frontend/src/App.tsx`
   - `frontend/src/components/layout/TopBar.tsx`
   - `frontend/src/App.css`

---

### Requirement 25: Unit and Property Testing

**User Story:** As a developer, I want comprehensive unit and property tests for all pure
functions, so that correctness is verified before visual integration.

#### Acceptance Criteria

1. THE `computeDensityGrid` function SHALL have unit tests that verify: correct bin assignment
   for boundary agents, `scale_units` accumulation (not raw agent count), and the conservation
   invariant (grid sum = total scale_units).
2. THE `computeDelta` function SHALL have unit tests that verify: correct `densityDelta` and
   `flowDelta` values for known inputs, skipping of missing keys, and the anti-symmetry
   property.
3. THE `routeConcentration` function SHALL have unit tests that verify: correct fraction for
   agents on the edge, zero return when no agents match, and zero return when `sim.agents`
   is empty.
4. THE `quickActionsFor` function SHALL have a unit test that verifies at least one action is
   always returned.
5. THE `suggestedPrompts` function SHALL have a unit test that verifies: the first prompt
   mentions the bottleneck location when `sim.bottlenecks` is non-empty, and the result length
   never exceeds 4.
6. THE `deltaColor` function SHALL have a property test verifying it always returns a non-empty
   string for any numeric density delta and flow delta inputs.
7. THE `AutoLoadBridge` SHALL have a unit test verifying the `didAutoLoad` guard fires
   `selectVenue` exactly once per mount.
8. THE property tests SHALL use `fast-check` as the property-based testing library.
