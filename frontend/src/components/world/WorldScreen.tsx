import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Activity, ArrowDownRight, ArrowLeft, ArrowUpRight, Bot, Eye, FlaskConical, Scan, Sparkles, X, ZoomIn } from 'lucide-react';
import { useSimulation } from '../../store/SimulationContext';
import DigitalTwinRenderer, { type CameraPreset, type TwinPick } from '../twin/DigitalTwinRenderer';
import TwinJobPanel from '../twin/TwinJobPanel';
import MapWorkspace from '../map/MapWorkspace';
import Timeline from '../workspace/Timeline';
import type { Bottleneck, ExternalEnvironment, Intervention, VenueModel, VenueSpatialModel, WorldGateState, WorldGraph, WorldState } from '../../lib/types';
import { api, twinArtifactUrl } from '../../lib/api';
import { riskState } from '../../lib/format';
import { BottleneckInvestigationPanel } from '../workspace/BottleneckInvestigationPanel';
import { edgeKey } from '../../lib/selection';
import { interventionTitle } from '../../lib/interventions';
import type { WorldTool, WorldView } from '../../lib/nav';
import HeaderBar from '../shell/HeaderBar';
import LeftRail from '../shell/LeftRail';
import RightRail from '../shell/RightRail';
import BottomBar from '../shell/BottomBar';
import { DEFAULT_ANCHOR, type GeoAnchor } from '../../lib/geoProjection';

function RiskBadge({ risk }: { risk: string }) {
  const s = riskState(risk as never);
  return (
    <span className={`chip ${s === 'danger' ? 'is-danger' : s === 'warn' ? 'is-warn' : 'is-ok'}`}>
      <span className={`status-dot ${s === 'danger' ? 'is-danger' : s === 'warn' ? 'is-warn' : 'is-ok'}`} />
      {risk}
    </span>
  );
}

const TOOLS: { id: WorldTool; label: string; icon: React.ReactNode; blurb: string }[] = [
  { id: 'live', label: 'LIVE', icon: <Activity className="h-3.5 w-3.5" />, blurb: 'What is happening now' },
  { id: 'predict', label: 'PREDICT', icon: <Eye className="h-3.5 w-3.5" />, blurb: 'Where the problem is heading' },
  { id: 'whatif', label: 'WHAT-IF', icon: <FlaskConical className="h-3.5 w-3.5" />, blurb: 'Test an intervention' },
  { id: 'optimize', label: 'OPTIMIZE', icon: <Sparkles className="h-3.5 w-3.5" />, blurb: 'Find the best flow' },
  { id: 'ai', label: 'AI', icon: <Bot className="h-3.5 w-3.5" />, blurb: 'Ask why + get interventions' },
];

const CAMERAS: { id: CameraPreset; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: 'OVERVIEW', icon: <Activity className="h-3 w-3" /> },
  { id: 'focus', label: 'FOCUS', icon: <ZoomIn className="h-3 w-3" /> },
  { id: 'follow', label: 'FOLLOW', icon: <Eye className="h-3 w-3" /> },
  { id: 'ground', label: 'GROUND', icon: <Scan className="h-3 w-3" /> },
];

// map an edge/node bottleneck location to a selectable spatial twin target
function bottleneckTwinPick(b: Bottleneck, venue: VenueModel | null, spatial: VenueSpatialModel | null): TwinPick | null {
  if (!spatial) return null;
  const loc = b.location;
  if (spatial.openings.some((o) => o.id === loc)) return { kind: 'opening', id: loc };
  if (spatial.paths.some((p) => p.id === loc)) return { kind: 'path', id: loc };
  if (spatial.structures.some((s) => s.id === loc)) return { kind: 'structure', id: loc };
  const [from, to] = loc.split('→');
  const node = venue?.nodes.find((n) => n.id === (to?.trim() ?? from?.trim()));
  if (node) {
    const opening = spatial.openings.find((o) => o.id === node.id || o.id.replace(/_/g, '') === node.id.replace(/_/g, ''));
    if (opening) return { kind: 'opening', id: opening.id };
    const path = spatial.paths.find((p) => p.id === node.id);
    if (path) return { kind: 'path', id: path.id };
    const struct = spatial.structures.find((s) => s.id === node.id);
    if (struct) return { kind: 'structure', id: struct.id };
  }
  return null;
}

// --------------------------------------------------------------------------- //
//  Shared contextual tool surfaces (work on the map AND inside the venue)
// --------------------------------------------------------------------------- //

function PredictCallout({ bottleneck, onRunWhatIf }: { bottleneck: Bottleneck; onRunWhatIf: () => void }) {
  return (
    <div className="absolute top-2 right-3 z-10 w-72 border border-od-warn bg-od-panel/95 px-3 py-2.5 shadow-lg backdrop-blur">
      <div className="flex items-center gap-2">
        <span className="status-dot is-warn" />
        <span className="sec-label">Projected congestion</span>
      </div>
      <div className="num mt-1.5 text-od-ink">{bottleneck.location.replace(/→/g, ' → ')}</div>
      <div className="mt-1 text-[10px] leading-snug text-od-muted">{bottleneck.explanation}</div>
      <div className="mt-2 flex items-center justify-between text-[10px] mono-tabular text-od-warn">
        <span>TTC</span>
        <span className="font-bold">
          {bottleneck.estimated_time_to_critical_min != null
            ? `${bottleneck.estimated_time_to_critical_min.toFixed(1)} min`
            : 'rising'}
        </span>
      </div>
      <button className="btn btn-solid mt-2 w-full" onClick={onRunWhatIf}>
        <FlaskConical className="h-3 w-3" /> TEST AN ALTERNATIVE
      </button>
    </div>
  );
}

function WhatIfToggle({ side, onChange }: { side: 'baseline' | 'whatif'; onChange: (s: 'baseline' | 'whatif') => void }) {
  return (
    <div className="absolute top-2 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1 border border-od-line bg-od-panel/95 px-1 py-1 shadow-lg backdrop-blur">
      <button className={`btn ${side === 'baseline' ? 'btn-solid' : 'btn-ghost'}`} onClick={() => onChange('baseline')}>
        BASELINE
      </button>
      <button className={`btn ${side === 'whatif' ? 'btn-solid' : 'btn-ghost'}`} onClick={() => onChange('whatif')}>
        WHAT-IF
      </button>
    </div>
  );
}

// --------------------------------------------------------------------------- //
//  What-if rerouting strip — REAL world gate flow, baseline vs counterfactual.
// --------------------------------------------------------------------------- //
const GATE_IDS = ['GATE_A', 'GATE_B', 'GATE_C', 'GATE_D', 'GATE_E', 'GATE_F'];

function WhatIfCompareStrip({ base, cf }: { base: WorldState | null; cf: WorldState | null }) {
  if (!base || !cf) return null;
  const rows = GATE_IDS
    .map((g) => ({ g, b: base.gates[g], c: cf.gates[g] }))
    .filter((r): r is { g: string; b: WorldGateState; c: WorldGateState } => !!r.b && !!r.c)
    .filter((r) => Math.abs(r.c.served_per_min - r.b.served_per_min) > 1 || Math.abs(r.c.queue - r.b.queue) > 4);
  if (rows.length === 0) return null;
  return (
    <div className="pointer-events-auto absolute top-2 left-1/2 z-10 w-[640px] max-w-[84vw] -translate-x-1/2 border border-od-line bg-od-panel/95 px-2.5 py-2 shadow-lg backdrop-blur">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="sec-label">What-if rerouting</span>
        <span className="text-[9px] uppercase tracking-[0.12em] text-od-muted">baseline → what-if · live gate flow</span>
      </div>
      <div className="grid grid-cols-3 gap-1.5 md:grid-cols-6">
        {rows.map(({ g, b, c }) => {
          const ds = Math.round(c.served_per_min - b.served_per_min);
          const dq = Math.round(c.queue - b.queue);
          const up = ds > 1;
          const down = ds < -1;
          return (
            <div key={g} className="border border-od-line bg-od-canvas/60 px-1.5 py-1 text-center">
              <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-od-muted">{g.replace('GATE_', 'G')}</div>
              <div className={`mt-0.5 flex items-center justify-center gap-0.5 text-[11px] mono-tabular font-bold ${up ? 'text-od-ok' : down ? 'text-od-danger' : 'text-od-muted'}`}>
                {up ? <ArrowUpRight className="h-3 w-3" /> : down ? <ArrowDownRight className="h-3 w-3" /> : null}
                {ds > 0 ? `+${ds}` : ds}
                <span className="text-[8px] font-normal text-od-muted">/min</span>
              </div>
              {dq !== 0 && (
                <div className={`text-[9px] mono-tabular ${dq > 0 ? 'text-od-warn' : 'text-od-ok'}`}>q {dq > 0 ? `+${dq}` : dq}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** What-if launcher: real interventions offered when no counterfactual exists. */
function WhatIfLauncher({
  gates,
  onRun,
  onClose,
}: {
  gates: { id: string; served: number; queue: number; risk: string }[];
  onRun: (iv: Intervention) => void;
  onClose: () => void;
}) {
  const press = gates[0] ?? null;
  const alt = gates[1] ?? null;
  const options: Intervention[] = [];
  if (press) {
    options.push(
      { id: `wi-close-${press.id}`, type: 'CHANGE_GATE', description: `Close ${press.id}`, parameters: { gate: press.id, capacity: 0, external: true } },
      { id: `wi-restrict-${press.id}`, type: 'CHANGE_GATE', description: `Restrict ${press.id} to 50/min`, parameters: { gate: press.id, capacity: 50, external: true } },
    );
    if (alt) {
      options.push(
        { id: `wi-redirect-${press.id}-${alt.id}`, type: 'REDIRECT', description: `Shift 30% of ${press.id} arrivals to ${alt.id}`, parameters: { from: press.id, to: alt.id, percent: 30, external: true } },
      );
    }
  }
  return (
    <motion.aside
      initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }}
      transition={{ duration: 0.18 }}
      className="absolute right-3 top-3 bottom-3 z-30 flex w-80 flex-col border border-od-line bg-od-panel/95 shadow-[0_24px_64px_-24px_rgba(0,0,0,0.8)] backdrop-blur"
    >
      <div className="flex shrink-0 items-center justify-between border-b border-od-line px-3 py-2">
        <span className="sec-label">What if…</span>
        <button onClick={onClose} className="cursor-pointer text-od-muted transition-colors hover:text-od-ink" aria-label="Close what-if launcher">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        <p className="text-[10px] leading-snug text-od-muted">
          Pick an intervention. CrowdFlow forks the live simulation and runs the real counterfactual.
        </p>
        {gates.length > 0 && (
          <div className="space-y-2">
            <div className="sec-label">Gates</div>
            {options.map((iv) => (
              <button key={iv.id} className="btn btn-ghost w-full justify-between" onClick={() => onRun(iv)}>
                <span className="text-left">{interventionTitle(iv)}</span>
                <FlaskConical className="h-3 w-3 shrink-0" />
              </button>
            ))}
          </div>
        )}
        <div className="space-y-2">
          <div className="sec-label">Live gate stress</div>
          <div className="space-y-1.5">
            {gates.slice(0, 4).map((g) => (
              <div key={g.id} className="flex items-center justify-between border border-od-line bg-od-canvas/60 px-2 py-1.5">
                <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-od-ink">{g.id.replace('GATE_', 'G')}</span>
                <span className="flex items-center gap-2 text-[10px] mono-tabular text-od-muted">
                  <span>{Math.round(g.served)}/min</span>
                  <span>q {Math.round(g.queue)}</span>
                  <RiskBadge risk={g.risk} />
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </motion.aside>
  );
}

// --------------------------------------------------------------------------- //
//  Timeline incident markers — recorded from real simulation state.
// --------------------------------------------------------------------------- //
type TimelineMarker = { t: number; label: string; tone: 'danger' | 'warn' | 'ok' | 'active' };

export default function WorldScreen() {
  const s = useSimulation();
  const [view, setView] = useState<WorldView>('map');
  const [tool, setTool] = useState<WorldTool>('live');
  const [pick, setPick] = useState<TwinPick | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [spatial, setSpatial] = useState<VenueSpatialModel | null>(null);
  const [spatialError, setSpatialError] = useState<string | null>(null);
  const [camera, setCamera] = useState<CameraPreset>('overview');
  const [whatifSide, setWhatifSide] = useState<'baseline' | 'whatif'>('whatif');
  const [env, setEnv] = useState<ExternalEnvironment | null>(null);
  const [envError, setEnvError] = useState<string | null>(null);
  const [world, setWorld] = useState<WorldGraph | null>(null);
  const [worldError, setWorldError] = useState<string | null>(null);
  const [twinPanelOpen, setTwinPanelOpen] = useState(false);
  const [speed, setSpeedLocal] = useState(1);
  const [railsOpen, setRailsOpen] = useState(true);

  // geo anchor (single source of truth shared with the map + right rail)
  const [anchor, setAnchor] = useState<GeoAnchor>(() => {
    try {
      const raw = localStorage.getItem('cf-geo-anchor');
      if (raw) return JSON.parse(raw) as GeoAnchor;
    } catch {
      /* ignore */
    }
    return DEFAULT_ANCHOR;
  });
  const handleAnchorChange = useCallback((a: GeoAnchor) => {
    setAnchor(a);
    localStorage.setItem('cf-geo-anchor', JSON.stringify(a));
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen();
  }, []);

  // twin renderer only understands the four sim modes; AI tool falls back to live
  const twinMode = tool === 'ai' ? 'live' : tool;

  // when the current venue was produced by a completed twin job, render its GLB.
  // AI meshes are arbitrary scale/orientation -> 'auto' fits them to the venue;
  // procedural GLBs are already in the world frame -> 'world' renders as-is.
  const glbUrl =
    s.twinJob?.status === 'COMPLETED' && s.venue && s.twinJob.venue_id === s.venue.id
      ? twinArtifactUrl(s.twinJob.id, 'venue.glb')
      : null;
  const glbMode = glbUrl && s.twinJob?.provenance === 'AI' ? 'auto' : 'world';

  // load the external road network / environment for the map workspace
  useEffect(() => {
    let cancelled = false;
    if (!s.venue) {
      setEnv(null);
      setEnvError(null);
      return;
    }
    setEnv(null);
    setEnvError(null);
    api
      .environment(s.venue.id)
      .then((e) => {
        if (!cancelled) setEnv(e);
      })
      .catch((e) => {
        if (!cancelled) setEnvError(e instanceof Error ? e.message : 'Failed to load environment');
      });
    return () => {
      cancelled = true;
    };
  }, [s.venue]);

  // load the unified world graph (external roads/footpaths + demand sources)
  useEffect(() => {
    let cancelled = false;
    if (!s.venue) {
      setWorld(null);
      setWorldError(null);
      return;
    }
    setWorld(null);
    setWorldError(null);
    api
      .worldGraph(s.venue.id)
      .then((w) => {
        if (!cancelled) setWorld(w);
      })
      .catch((e) => {
        if (!cancelled) setWorldError(e instanceof Error ? e.message : 'Failed to load world graph');
      });
    return () => {
      cancelled = true;
    };
  }, [s.venue]);
  useEffect(() => {
    let cancelled = false;
    if (!s.venue) {
      setSpatial(null);
      setSpatialError(null);
      return;
    }
    setSpatial(null);
    setSpatialError(null);
    api
      .venueSpatial(s.venue.id)
      .then((sp) => {
        if (!cancelled) setSpatial(sp);
      })
      .catch((e) => {
        if (!cancelled) setSpatialError(e instanceof Error ? e.message : 'Failed to load spatial twin');
      });
    return () => {
      cancelled = true;
    };
  }, [s.venue]);

  // the sim shown (live sim, or the what-if comparison side)
  const activeBottlenecks: Bottleneck[] =
    tool === 'whatif' && whatifSide === 'whatif' && s.cfSim?.bottlenecks?.length
      ? s.cfSim.bottlenecks
      : (s.displayedSim?.bottlenecks ?? []);

  const topBottleneck = activeBottlenecks[0] ?? null;

  // picking a bottleneck opens the inspector over the current surface (map or
  // venue); the venue view focuses the camera on it when visible
  const handleBottleneckSelect = useCallback(
    (b: Bottleneck) => {
      const t = bottleneckTwinPick(b, s.venue, spatial);
      setPick(t);
      setInspectorOpen(true);
      setCamera('focus');
    },
    [s.venue, spatial],
  );

  const handlePick = useCallback((t: TwinPick | null) => {
    setPick(t);
    setInspectorOpen(t != null);
    if (t) setCamera('focus');
  }, []);

  // draft an intervention from the selected bottleneck / AI suggestions
  const [drafts, setDrafts] = useState<{ closedEdgeIds: string[]; redirect: { from: string; to: string; pct: number } | null } | null>(null);

  const runWhatIf = useCallback(
    async (intervention?: Intervention) => {
      const iv: Intervention =
        intervention ??
        (() => {
          const loc = topBottleneck?.location;
          return {
            id: typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}`,
            type: 'CLOSE_CORRIDOR',
            description: `Close ${loc} — test an alternative route`,
            parameters: { edge: loc },
          };
        })();
      if (!iv || !s.runCounterfactual) return;
      await s.runCounterfactual(iv);
      setWhatifSide('whatif');
      setTool('whatif');
    },
    [topBottleneck, s],
  );

  // gate stress summary for the what-if launcher (real world state)
  const gateStress = useMemo(() => {
    const w = s.displayedSim?.world;
    if (!w) return [];
    return GATE_IDS
      .map((g) => ({ id: g, ...w.gates[g] }))
      .filter((g) => g && g.served_per_min != null)
      .sort((a, b) => b.queue - a.queue || b.served_per_min - a.served_per_min)
      .map((g) => ({ id: g.id, served: g.served_per_min, queue: g.queue, risk: g.risk }));
  }, [s.displayedSim?.world]);

  // ── timeline incident markers, recorded from real simulation state ──────── //
  const [markers, setMarkers] = useState<TimelineMarker[]>([]);
  const incidentRef = useRef<{ gate: Record<string, number>; pred: Record<string, number>; eased: Record<string, number>; ivCount: number }>({
    gate: {},
    pred: {},
    eased: {},
    ivCount: 0,
  });
  const prevGateRisk = useRef<Record<string, string>>({});

  useEffect(() => {
    incidentRef.current = { gate: {}, pred: {}, eased: {}, ivCount: 0 };
    prevGateRisk.current = {};
    setMarkers([]);
  }, [s.simId]);

  useEffect(() => {
    const st = s.displayedSim;
    if (!st) return;
    const t = st.t_min;
    const w = st.world;
    const inc = incidentRef.current;
    const fresh: TimelineMarker[] = [];
    if (w) {
      for (const [g, gs] of Object.entries(w.gates)) {
        const r = gs.risk;
        const prev = prevGateRisk.current[g];
        if (prev && prev !== r) {
          if ((r === 'HIGH' || r === 'CRITICAL') && !inc.gate[g]) {
            inc.gate[g] = t;
            fresh.push({ t, label: `${g.replace('GATE_', 'Gate ')} ${r}`, tone: r === 'CRITICAL' ? 'danger' : 'warn' });
          }
          if ((prev === 'HIGH' || prev === 'CRITICAL') && r === 'NORMAL' && !inc.eased[g]) {
            inc.eased[g] = t;
            fresh.push({ t, label: `Rerouting · ${g.replace('GATE_', 'Gate ')} eased`, tone: 'ok' });
          }
        }
        prevGateRisk.current[g] = r;
      }
      for (const p of w.predictions) {
        if (!inc.pred[p.id]) {
          inc.pred[p.id] = t;
          fresh.push({ t, label: `Prediction · ${p.ref.replace('GATE_', 'Gate ')}`, tone: 'danger' });
        }
      }
    }
    const ivs = s.sim?.interventions_applied ?? [];
    if (ivs.length > inc.ivCount) {
      for (let i = inc.ivCount; i < ivs.length; i++) {
        fresh.push({ t, label: `Intervention · ${interventionTitle(ivs[i])}`, tone: 'active' });
      }
      inc.ivCount = ivs.length;
    }
    if (fresh.length) setMarkers((m) => [...m, ...fresh]);
  }, [s.displayedSim, s.sim?.interventions_applied]);

  const applyDraft = useCallback(() => {
    if (drafts?.redirect) {
      s.applyIntervention({
        id: typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}`,
        type: 'REDIRECT',
        description: `Redirect ${drafts.redirect.from} → ${drafts.redirect.to} (${drafts.redirect.pct}%)`,
        parameters: { from: drafts.redirect.from, to: drafts.redirect.to, pct: drafts.redirect.pct },
      } as Intervention);
    } else if (drafts?.closedEdgeIds.length) {
      s.applyIntervention({
        id: typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}`,
        type: 'CLOSE_CORRIDOR',
        description: `Close ${drafts.closedEdgeIds[0]}`,
        parameters: { edge: drafts.closedEdgeIds[0] },
      } as Intervention);
    }
    setDrafts(null);
    setTool('live');
  }, [drafts, s]);

  const handleTool = useCallback((t: WorldTool) => {
    setTool(t);
    if (t === 'predict') setCamera('focus');
    // WHAT-IF opens the intervention launcher (or the running comparison);
    // no simulation is forked until the user picks an intervention.
  }, []);

  // inspect an opened panel on the selected bottleneck
  const selectedBottleneck = useMemo(() => {
    if (!pick) return null;
    return activeBottlenecks.find(
      (b) =>
        b.location === pick.id ||
        (pick.kind === 'opening' && b.location.includes(pick.id)) ||
        (pick.kind === 'structure' && b.location.includes(pick.id)),
    );
  }, [pick, activeBottlenecks]);

  // element state for the inspector (live sim)
  const elementState = selectedBottleneck && s.displayedSim
    ? (s.displayedSim.edges[selectedBottleneck.location] ?? s.displayedSim.nodes[selectedBottleneck.location])
    : null;
  const venueElement = selectedBottleneck && s.venue
    ? (s.venue.edges.find((e) => edgeKey(e.source, e.destination) === selectedBottleneck.location) ??
       s.venue.nodes.find((n) => n.id === selectedBottleneck.location))
    : null;

  const onApplySpeed = useCallback(
    (sp: number) => {
      setSpeedLocal(sp);
      void s.setSpeed(sp);
    },
    [s],
  );

  const showTransport = s.simId != null;
  const draftPending = !!(drafts?.closedEdgeIds.length || drafts?.redirect);

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-od-canvas">
      {/* ── top command bar ──────────────────────────────────────────── */}
      <HeaderBar
        railsOpen={railsOpen}
        onToggleRails={() => setRailsOpen((o) => !o)}
        twinPanelOpen={twinPanelOpen}
        onToggleTwinPanel={() => setTwinPanelOpen((o) => !o)}
        onCloseEvent={() => void s.clearSimulation()}
        onToggleFullscreen={toggleFullscreen}
        tool={tool}
      />

      {/* ── command grid: left config rail / live viewport / right analysis rail ── */}
      <div className="flex min-h-0 flex-1">
        {railsOpen && <LeftRail onEnterVenue={() => setView('venue')} onBuildTwin={() => setTwinPanelOpen(true)} />}

        <div className="relative min-w-0 flex-1">
          {view === 'map' ? (
            s.venue && (env || world) ? (
              <>
                <MapWorkspace
                  venue={s.venue}
                  env={env}
                  world={world}
                  sim={s.displayedSim}
                  cfSim={tool === 'whatif' ? s.cfSim : null}
                  worldState={s.displayedSim?.world ?? null}
                  cfWorldState={tool === 'whatif' ? (s.cfSim?.world ?? null) : null}
                  compareSide={whatifSide}
                  anchor={anchor}
                  onAnchorChange={handleAnchorChange}
                  onOpenVenue={() => setView('venue')}
                  onSelectBottleneck={handleBottleneckSelect}
                />
                {tool === 'predict' && topBottleneck && (
                  <PredictCallout bottleneck={topBottleneck} onRunWhatIf={() => void runWhatIf()} />
                )}
                {tool === 'whatif' && !s.cfSim && (
                  <WhatIfLauncher gates={gateStress} onRun={(iv) => void runWhatIf(iv)} onClose={() => setTool('live')} />
                )}
                {tool === 'whatif' && s.cfSim && (
                  <>
                    <WhatIfToggle side={whatifSide} onChange={setWhatifSide} />
                    <WhatIfCompareStrip base={s.displayedSim?.world ?? null} cf={s.cfSim.world ?? null} />
                  </>
                )}

                {/* first-run / not started gate over the map */}
                {s.venue && !s.sim && (
                  <div className="absolute inset-0 z-20 flex items-center justify-center" style={{ backdropFilter: 'blur(2px)', background: 'rgba(10,12,14,0.45)' }}>
                    <div className="space-y-3 px-8 text-center">
                      <div className="font-display text-[18px] font-bold uppercase tracking-[0.24em] text-od-ink">
                        {s.venue.name}
                      </div>
                      {s.scenario && (
                        <div className="text-[11px] text-od-muted">
                          {s.scenario.name} · {s.scenario.crowd_size.toLocaleString()} expected
                        </div>
                      )}
                      <button className="btn btn-solid h-14 px-10 text-base font-bold" onClick={() => void s.runSimulation()} disabled={!s.scenario}>
                        ▶ RUN LIVE SCENARIO
                      </button>
                    </div>
                  </div>
                )}
              </>
            ) : view === 'map' && (envError || worldError) ? (
              <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center" role="alert">
                <span className="text-[11px] font-bold uppercase tracking-[0.16em] text-od-danger">Map environment unavailable</span>
                <span className="text-[10px] text-od-muted mono-tabular">{envError ?? worldError}</span>
                <button
                  className="btn btn-solid"
                  onClick={() => {
                    if (!s.venue) return;
                    api.environment(s.venue.id).then(setEnv).catch((err) => setEnvError(String(err)));
                    api.worldGraph(s.venue.id).then(setWorld).catch((err) => setWorldError(String(err)));
                  }}
                >
                  Retry
                </button>
              </div>
            ) : view === 'map' ? (
              <div className="flex h-full items-center justify-center">
                <div className="shimmer-line h-3 w-44" />
              </div>
            ) : null
          ) : spatial && s.venue ? (
            <motion.div
              className="absolute inset-0"
              initial={{ opacity: 0, scale: 1.015 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.28, ease: 'easeOut' }}
            >
              {tool === 'whatif' && s.cfSim ? (
                /* split-screen comparison: baseline (live sim) vs what-if (forked counterfactual) */
                <div className="flex h-full w-full">
                  <div className="relative min-w-0 flex-1">
                    <div className="absolute top-2 left-1/2 z-10 -translate-x-1/2">
                      <span className="chip is-ok">BASELINE</span>
                    </div>
                    <DigitalTwinRenderer
                      venue={s.venue}
                      spatial={spatial}
                      sim={s.displayedSim}
                      simRef={s.simRef}
                      mode="live"
                      compareSim={null}
                      compareSide="baseline"
                      bottlenecks={s.displayedSim?.bottlenecks ?? []}
                      selected={pick}
                      onPick={handlePick}
                      cameraPreset={camera}
                      onCameraPresetChange={setCamera}
                      onBottleneckSelect={handleBottleneckSelect}
                      glbUrl={glbUrl}
                      glbMode={glbMode}
                    />
                  </div>
                  <div className="relative z-10 w-px shrink-0 bg-od-warn/60" />
                  <div className="relative min-w-0 flex-1">
                    <div className="absolute top-2 left-1/2 z-10 -translate-x-1/2">
                      <span className="chip is-warn">WHAT-IF</span>
                    </div>
                    <DigitalTwinRenderer
                      venue={s.venue}
                      spatial={spatial}
                      sim={s.cfSim}
                      simRef={s.cfSimRef}
                      mode="whatif"
                      compareSim={null}
                      compareSide="baseline"
                      bottlenecks={s.cfSim?.bottlenecks ?? []}
                      selected={pick}
                      onPick={handlePick}
                      cameraPreset={camera}
                      onCameraPresetChange={setCamera}
                      onBottleneckSelect={handleBottleneckSelect}
                      glbUrl={glbUrl}
                      glbMode={glbMode}
                    />
                  </div>
                </div>
              ) : (
                <DigitalTwinRenderer
                  venue={s.venue}
                  spatial={spatial}
                  sim={s.displayedSim}
                  simRef={s.simRef}
                  mode={twinMode}
                  compareSim={tool === 'whatif' ? s.cfSim : null}
                  compareSide={whatifSide}
                  bottlenecks={activeBottlenecks}
                  selected={pick}
                  onPick={handlePick}
                  cameraPreset={camera}
                  onCameraPresetChange={setCamera}
                  onBottleneckSelect={handleBottleneckSelect}
                  glbUrl={glbUrl}
                  glbMode={glbMode}
                />
              )}

              {/* back to map */}
              <button
                className="absolute top-2 left-3 z-10 btn btn-ghost"
                onClick={() => setView('map')}
                title="Back to the live map"
              >
                <ArrowLeft className="h-3.5 w-3.5" /> MAP
              </button>

              {tool === 'predict' && topBottleneck && (
                <PredictCallout bottleneck={topBottleneck} onRunWhatIf={() => void runWhatIf()} />
              )}
              {tool === 'whatif' && !s.cfSim && (
                <WhatIfLauncher gates={gateStress} onRun={(iv) => void runWhatIf(iv)} onClose={() => setTool('live')} />
              )}
              {tool === 'whatif' && s.cfSim && (
                <>
                  <WhatIfToggle side={whatifSide} onChange={setWhatifSide} />
                  <WhatIfCompareStrip base={s.displayedSim?.world ?? null} cf={s.cfSim.world ?? null} />
                  <div className="absolute bottom-3 left-1/2 z-10 -translate-x-1/2 flex items-center gap-2">
                    <button className="btn btn-ghost" onClick={s.discardCounterfactual}>DISCARD</button>
                    <button className="btn btn-solid" onClick={() => void s.applyCounterfactual()}>APPLY TO LIVE</button>
                  </div>
                </>
              )}

              {/* camera preset rail (bottom-left, over the twin) */}
              <div className="absolute bottom-3 left-3 z-10 flex items-center gap-1 border border-od-line bg-od-panel/90 px-1 py-1 backdrop-blur">
                {CAMERAS.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => setCamera(c.id)}
                    aria-pressed={camera === c.id}
                    title={c.label}
                    className={`rail-btn !px-2 ${camera === c.id ? 'is-active' : ''}`}
                  >
                    {c.icon}
                    <span className="hidden md:inline">{c.label}</span>
                  </button>
                ))}
              </div>

              {/* first-run / not started gate */}
              {s.venue && !s.sim && spatial && (
                <div className="absolute inset-0 z-20 flex items-center justify-center" style={{ backdropFilter: 'blur(2px)', background: 'rgba(10,12,14,0.5)' }}>
                  <div className="space-y-3 px-8 text-center">
                    <div className="sec-label">{s.venue.name} · Digital Twin</div>
                    {s.scenario && <div className="text-[11px] text-od-muted">{s.scenario.name} · {s.scenario.crowd_size.toLocaleString()} crowd</div>}
                    <button className="btn btn-solid h-14 px-10 text-base font-bold" onClick={() => void s.runSimulation()}>▶ RUN LIVE SCENARIO</button>
                  </div>
                </div>
              )}
            </motion.div>
          ) : spatialError ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center" role="alert">
              <span className="text-[11px] font-bold uppercase tracking-[0.16em] text-od-danger">Spatial twin unavailable</span>
              <span className="text-[10px] text-od-muted mono-tabular">{spatialError}</span>
              <button className="btn btn-solid" onClick={() => s.venue && void api.venueSpatial(s.venue.id).then(setSpatial).catch((e) => setSpatialError(String(e)))}>
                Retry
              </button>
            </div>
          ) : (
            <div className="flex h-full items-center justify-center">
              <div className="shimmer-line h-3 w-44" />
            </div>
          )}

          {/* ── contextual inspector (over the map or the twin, progressive disclosure) ── */}
          <AnimatePresence>
            {inspectorOpen && pick && selectedBottleneck && elementState && venueElement && s.displayedSim && s.venue ? (
              <motion.aside
                initial={{ opacity: 0, x: 24 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 24 }}
                transition={{ duration: 0.18 }}
                className="absolute right-3 top-3 bottom-3 z-30 flex w-80 flex-col border border-od-line bg-od-panel/95 shadow-[0_24px_64px_-24px_rgba(0,0,0,0.8)] backdrop-blur"
              >
                <div className="flex shrink-0 items-center justify-between border-b border-od-line px-3 py-2">
                  <span className="sec-label">Bottleneck</span>
                  <button onClick={() => handlePick(null)} className="cursor-pointer text-od-muted transition-colors hover:text-od-ink" aria-label="Close inspector">
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-3">
                  <BottleneckInvestigationPanel
                    bottleneck={selectedBottleneck}
                    elementState={elementState}
                    venueElement={venueElement}
                    sim={s.displayedSim}
                    venue={s.venue}
                    onDraftIntervention={(i) => {
                      const edge = i.parameters?.edge;
                      const from = i.parameters?.from;
                      setDrafts(edge ? { closedEdgeIds: [String(edge)], redirect: null } : from ? { closedEdgeIds: [], redirect: { from: String(from), to: String(i.parameters?.to ?? ''), pct: Number(i.parameters?.pct ?? 15) } } : { closedEdgeIds: [], redirect: null });
                      setTool('whatif');
                    }}
                    onExplainAi={() => void s.explainCurrent()}
                    aiExplanation={s.aiExplanation}
                    aiBusy={s.aiBusy}
                    aiConfigured={s.aiConfigured}
                    aiError={s.aiError}
                  />
                </div>
              </motion.aside>
            ) : inspectorOpen && pick ? (
              <motion.aside
                initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }}
                transition={{ duration: 0.18 }}
                className="absolute right-3 top-3 bottom-3 z-30 flex w-80 flex-col border border-od-line bg-od-panel/95 shadow-lg backdrop-blur"
              >
                <div className="flex shrink-0 items-center justify-between border-b border-od-line px-3 py-2">
                  <span className="sec-label">Inspect</span>
                  <button onClick={() => handlePick(null)} className="cursor-pointer text-od-muted hover:text-od-ink" aria-label="Close inspector">
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="min-h-0 flex-1 px-3 py-3">
                  <div className="num truncate text-[13px] font-bold uppercase tracking-[0.04em] text-od-ink">
                    {pick.id.replace(/_/g, ' ')}
                  </div>
                  <div className="meta mt-0.5">{pick.kind} · no live element</div>
                </div>
              </motion.aside>
            ) : null}
          </AnimatePresence>

          {/* AI 3D digital twin builder — reachable in every state (no venue needed) */}
          {twinPanelOpen && (
            <div className="absolute inset-y-0 right-0 z-50">
              <TwinJobPanel onClose={() => setTwinPanelOpen(false)} />
            </div>
          )}

          {/* no venue yet */}
          {!s.venue && (
            <div className="absolute inset-0 z-20 flex items-center justify-center">
              <div className="space-y-3 text-center">
                <div className="sec-label">Loading digital twin…</div>
                <div className="shimmer-line h-3 w-40 mx-auto" />
              </div>
            </div>
          )}
        </div>

        {railsOpen && (
          <RightRail
            anchor={anchor}
            onReAnchor={() => setView('map')}
            onRunWhatIf={(iv) => void runWhatIf(iv)}
            activeSection={tool}
          />
        )}
      </div>

      {/* ── simulation timeline (scrub back/forth through the event) ── */}
      {showTransport && (
        <Timeline
          buffer={s.buffer}
          frameIndex={s.frameIndex}
          seeking={s.seeking}
          tMin={s.displayedSim?.t_min ?? 0}
          status={s.sim?.status ?? ''}
          phases={s.scenario?.event_phases ?? []}
          speed={speed}
          speeds={[1, 2, 4, 8]}
          onSeek={s.seekFrame}
          onJump={s.jumpToMinute}
          onPlay={() => void s.play()}
          onPause={() => void s.pause()}
          onRewind={() => void s.jumpToMinute(0)}
          onSpeed={onApplySpeed}
          simId={s.simId}
          markers={markers}
        />
      )}

      {/* ── bottom navigation + contextual actions ── */}
      <BottomBar
        tools={TOOLS}
        tool={tool}
        onToolChange={handleTool}
        view={view}
        onViewChange={setView}
        canEnterVenue={!!spatial && !!s.venue}
        onJumpToMinute={s.jumpToMinute}
        draftPending={draftPending}
        onApplyDraft={applyDraft}
        onClearDraft={() => setDrafts(null)}
        cfSimId={s.cfSimId}
        onApplyCf={() => void s.applyCounterfactual()}
        onDiscardCf={s.discardCounterfactual}
      />
    </div>
  );
}