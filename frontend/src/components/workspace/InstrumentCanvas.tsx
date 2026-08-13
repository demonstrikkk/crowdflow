import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Boxes, PanelsTopLeft, RefreshCw } from 'lucide-react';
import { motion } from 'framer-motion';
import type { ExternalEnvironment, SimulationState, VenueModel } from '../../lib/types';
import { elementColor } from '../../lib/format';
import { edgeKey, positionsOf, type Mode, type Selection } from '../../lib/selection';
import type { GuidedStep } from '../../store/SimulationContext';
import { InstrumentCanvasAgents } from './InstrumentCanvasAgents';
import { DensityGridLayer } from './DensityGridLayer';
import { FlowArrowLayer } from './FlowArrowLayer';
import { BottleneckPulseLayer } from './BottleneckPulseLayer';

export interface RedirectDraft {
  from: string;
  to: string;
  pct: number;
}

export interface DraftState {
  closedEdgeIds: string[];
  redirect: RedirectDraft | null;
}

export type CanvasScope = 'venue' | 'surround' | 'network';

/** Spatial action issued from the venue itself (the world is the interface). */
export type SpatialAction =
  | { type: 'close'; selection: Selection }
  | { type: 'open'; selection: Selection }
  | { type: 'redirect'; selection: Selection }
  | { type: 'incident'; selection: Selection };

export interface CanvasProps {
  sim: SimulationState | null;
  venue: VenueModel | null;
  mode: Mode;
  selected: Selection | null;
  onSelect?: (sel: Selection | null) => void;
  interactive?: boolean;
  showAgents?: boolean;
  showLabels?: boolean;
  guided?: GuidedStep;
  drafts?: DraftState | null;
  environment?: ExternalEnvironment | null;
  scope?: CanvasScope;
  onScope?: (s: CanvasScope) => void;
  onRefreshEnvironment?: () => void;
  onSpatialAction?: (action: SpatialAction) => void;
  /** simRef from SimulationContext for rAF-based Canvas2D agent rendering */
  simRef?: React.RefObject<SimulationState | null>;
  /** viewMode for density/crowd heatmap visibility */
  viewMode?: string;
}

const NODE_KIND: Record<string, string> = {
  ENTRY: 'GATE',
  EXIT: 'EXIT',
  EMERGENCY_EXIT: 'EMERGENCY',
  INTERSECTION: 'JUNCTION',
  CONCESSION: 'CONCESSION',
  CHECKPOINT: 'CHECKPOINT',
  ZONE: 'ZONE',
};

// isometric basis vectors (2.5D): screen-x along (1,-1), screen-y along (1,1)
const ISO_C = 0.8660254037844386; // cos 30°
const ISO_S = 0.5; // sin 30°

function toIso(x: number, y: number) {
  return { x: (x - y) * ISO_C, y: (x + y) * ISO_S };
}

function fromIso(sx: number, sy: number) {
  return { x: (sy / ISO_S + sx / ISO_C) / 2, y: (sy / ISO_S - sx / ISO_C) / 2 };
}

function ptSegDist(px: number, py: number, x1: number, y1: number, x2: number, y2: number) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const l2 = dx * dx + dy * dy;
  if (l2 === 0) return Math.hypot(px - x1, py - y1);
  let t = ((px - x1) * dx + (py - y1) * dy) / l2;
  t = Math.max(0, Math.min(1, t));
  const cx = x1 + t * dx;
  const cy = y1 + t * dy;
  return Math.hypot(px - cx, py - cy);
}

export default function InstrumentCanvas({
  sim,
  venue,
  mode,
  selected,
  onSelect,
  interactive = true,
  showAgents = true,
  showLabels = true,
  guided = 'idle',
  drafts = null,
  environment = null,
  scope = 'venue',
  onScope,
  onRefreshEnvironment,
  onSpatialAction,
  simRef,
  viewMode = 'command',
}: CanvasProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<Selection | null>(null);
  const [iso, setIso] = useState(false);
  const [ring, setRing] = useState<{ x: number; y: number } | null>(null);
  // Canvas 2D fallback flag (Req 19)
  const [canvasSupported, setCanvasSupported] = useState(true);

  const W = venue?.width ?? 1000;
  const H = venue?.height ?? 620;
  const m = Math.min(W, H);
  const nodeR = m / 46;

  const pos = useMemo(() => positionsOf(venue, sim?.node_positions), [venue, sim?.node_positions]);
  const nodeState = useMemo(() => new Map(Object.entries(sim?.nodes ?? {})), [sim?.nodes]);
  const edgeState = useMemo(() => new Map(Object.entries(sim?.edges ?? {})), [sim?.edges]);
  const edges = useMemo(() => venue?.edges ?? [], [venue]);

  const riskColoring = mode === 'simulate' || mode === 'investigate';
  const showDensity = riskColoring;

  const closedKeys = useMemo(
    () => new Set(edges.filter((e) => !e.is_open).map((e) => edgeKey(e.source, e.destination))),
    [edges],
  );

  const highlightEdgeId = sim && sim.bottlenecks.length > 0 ? sim.bottlenecks[0].location : null;
  const guidedEdge =
    guided === 'bottleneck' && highlightEdgeId && (riskColoring || mode === 'intervene')
      ? highlightEdgeId
      : null;

  // ------------------------------------------------------------------ //
  //  2.5D framing: compute the iso viewBox, group matrix, projected
  //  corners and wall extrusion so the venue reads as a raised slab.
  // ------------------------------------------------------------------ //
  const pad = m * 0.05;
  const wallPx = m * 0.13;
  const isoTransform = useMemo(() => {
    if (!iso) return { matrix: '', viewBox: `0 0 ${W} ${H}`, tx: 0, ty: 0 };
    const minX = -H * ISO_C;
    const maxX = W * ISO_C;
    const maxY = (W + H) * ISO_S;
    const tx = -minX + pad;
    const ty = wallPx + pad;
    const viewBox = `${minX - pad} ${-wallPx - pad} ${maxX - minX + pad * 2} ${maxY + wallPx + pad * 2}`;
    return { matrix: `matrix(${ISO_C}, ${ISO_S}, ${-ISO_C}, ${ISO_S}, ${tx}, ${ty})`, viewBox, tx, ty };
  }, [iso, W, H, pad, wallPx]);

  const proj = useMemo(() => {
    if (!iso) return pos;
    const out = new Map<string, { x: number; y: number }>();
    for (const [id, p] of pos) {
      const q = toIso(p.x, p.y);
      out.set(id, { x: q.x + isoTransform.tx, y: q.y + isoTransform.ty });
    }
    return out;
  }, [iso, pos, isoTransform]);

  // bounding box of the environment for SURROUND (ring + access) / NETWORK (all)
  const scopeBox = useMemo(() => {
    if (!environment || scope === 'venue' || environment.roads.length === 0) return null;
    const included =
      scope === 'network'
        ? environment.roads
        : environment.roads.filter((r) => r.kind === 'RING' || r.kind === 'ACCESS');
    const pts: { x: number; y: number }[] = [];
    for (const r of included) for (const p of r.points) pts.push(p);
    for (const j of environment.junctions) pts.push(j.position);
    for (const t of environment.transit) pts.push(t.position);
    for (const p of environment.parking) pts.push(p.position);
    if (pts.length === 0) return null;
    const pad = m * 0.06;
    const minX = Math.min(...pts.map((p) => p.x)) - pad;
    const minY = Math.min(...pts.map((p) => p.y)) - pad;
    const maxX = Math.max(...pts.map((p) => p.x)) + pad;
    const maxY = Math.max(...pts.map((p) => p.y)) + pad;
    return { minX, minY, maxX, maxY };
  }, [environment, scope, m]);

  const activeViewBox = useMemo(() => {
    if (iso) return isoTransform.viewBox;
    if (scopeBox) return `${scopeBox.minX} ${scopeBox.minY} ${scopeBox.maxX - scopeBox.minX} ${scopeBox.maxY - scopeBox.minY}`;
    return `0 0 ${W} ${H}`;
  }, [iso, isoTransform, scopeBox, W, H]);

  // congestion lookup for the surrounding road elements
  const extState = useMemo(() => new Map(Object.entries(sim?.external?.elements ?? {})), [sim?.external?.elements]);

  // anchor the spatial action ring at the selected element's screen position
  useLayoutEffect(() => {
    const svg = svgRef.current;
    const root = rootRef.current;
    if (!svg || !root || !selected || mode !== 'intervene' || !interactive) {
      setRing(null);
      return;
    }
    const ctm = svg.getScreenCTM();
    if (!ctm) {
      setRing(null);
      return;
    }
    let anchor: { x: number; y: number } | null = null;
    const projAt = (id: string) => proj.get(id) ?? null;
    if (selected.kind === 'node') {
      anchor = projAt(selected.id);
    } else {
      const e = venue?.edges.find((x) => edgeKey(x.source, x.destination) === selected.id);
      if (e) {
        const a = projAt(e.source);
        const b = projAt(e.destination);
        if (a && b) anchor = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      }
    }
    if (!anchor) {
      setRing(null);
      return;
    }
    const pt = new DOMPoint(anchor.x, anchor.y).matrixTransform(ctm);
    const r = root.getBoundingClientRect();
    setRing({ x: pt.x - r.left, y: pt.y - r.top });
  }, [selected, iso, mode, interactive, venue, proj]);

  const isoFloor = useMemo(() => {
    if (!iso) return null;
    const corners = [
      toIso(0, 0),
      toIso(W, 0),
      toIso(W, H),
      toIso(0, H),
    ].map((p) => ({ x: p.x + isoTransform.tx, y: p.y + isoTransform.ty }));
    return corners;
  }, [iso, W, H, isoTransform]);

  const hitTest = (px: number, py: number): Selection | null => {
    let bestEdge: Selection | null = null;
    let bestEdgeD = Infinity;
    let bestNode: Selection | null = null;
    let bestNodeD = Infinity;
    const edgeHitR = Math.max(6, nodeR * 1.3);
    for (const e of edges) {
      const s = pos.get(e.source);
      const d = pos.get(e.destination);
      if (!s || !d) continue;
      const dist = ptSegDist(px, py, s.x, s.y, d.x, d.y);
      if (dist <= edgeHitR && dist < bestEdgeD) {
        bestEdgeD = dist;
        bestEdge = { kind: 'edge', id: edgeKey(e.source, e.destination) };
      }
    }
    for (const n of venue?.nodes ?? []) {
      const p = pos.get(n.id);
      if (!p) continue;
      const dist = Math.hypot(px - p.x, py - p.y);
      if (dist <= nodeR * 1.9 && dist < bestNodeD) {
        bestNodeD = dist;
        bestNode = { kind: 'node', id: n.id };
      }
    }
    if (bestNodeD < nodeR * 1.0 && bestNodeD <= bestEdgeD + nodeR * 0.25) return bestNode;
    return bestNodeD <= bestEdgeD ? bestNode : bestEdge;
  };

  const toViewBox = (clientX: number, clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return null;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const p = new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
  };

  const toVenueSpace = (sx: number, sy: number) => {
    if (!iso) return { x: sx, y: sy };
    return fromIso(sx - isoTransform.tx, sy - isoTransform.ty);
  };

  const handlePointer = (e: React.PointerEvent<SVGSVGElement>, select: boolean) => {
    if (!interactive || !onSelect) return;
    const pt = toViewBox(e.clientX, e.clientY);
    if (!pt) return;
    const v = toVenueSpace(pt.x, pt.y);
    const hit = hitTest(v.x, v.y);
    if (select) onSelect(hit);
    else setHover(hit);
  };

  if (!venue) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-od-canvas">
        <span className="text-[11px] uppercase tracking-[0.24em] text-od-muted">
          No venue selected
        </span>
      </div>
    );
  }

  const selectedEdge = selected?.kind === 'edge' ? selected.id : null;
  const selectedNode = selected?.kind === 'node' ? selected.id : null;
  const drawnEdges = edges.map((e) => {
    const s = pos.get(e.source);
    const d = pos.get(e.destination);
    if (!s || !d) return null;
    const key = edgeKey(e.source, e.destination);
    const st = edgeState.get(key);
    const util = st?.utilisation ?? 0;
    const hot = guidedEdge === key;
    const sel = selectedEdge === key;
    const closedDraft = drafts?.closedEdgeIds.includes(key) ?? false;
    const redirectDraft = drafts?.redirect && (drafts.redirect.from === e.source || drafts.redirect.to === e.source || drafts.redirect.from === e.destination || drafts.redirect.to === e.destination);
    const hovered = hover?.kind === 'edge' && hover.id === key;

    const base = m / 450;
    let width = sel ? m / 95 : hot || hovered ? m / 130 : base;
    let stroke = 'var(--od-line)';
    let opacity = 0.55;
    let dash: string | undefined;
    if (closedKeys.has(key)) {
      stroke = 'var(--od-line)';
      dash = '6 4';
      opacity = 0.35;
    }
    if (st && showDensity && st.risk !== 'NORMAL') {
      stroke = elementColor(st.risk, util);
      width = Math.max(width, base + (showDensity ? util * (m / 150) : 0));
      opacity = Math.max(opacity, 0.5 + util * 0.4);
    }
    if (sel) opacity = 1;
    if (hot) {
      stroke = 'var(--od-warn)';
      opacity = 0.95;
    }
    if (closedDraft) {
      stroke = 'var(--od-danger)';
      dash = '3 3';
      width = m / 110;
      opacity = 1;
    }

    const mid = { x: (s.x + d.x) / 2, y: (s.y + d.y) / 2 };
    return { e, key, s, d, mid, st, util, width, stroke, opacity, dash, sel, hot, closedDraft, redirectDraft, hovered };
  });

  const agentShadowOffset = iso ? Math.max(1, nodeR * 0.22) : 0;

  return (
    <div ref={rootRef} className="od-grid-canvas relative h-full w-full overflow-hidden">
      <svg
        ref={svgRef}
        viewBox={activeViewBox}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`Venue map for ${venue.name}`}
        className="h-full w-full"
        onPointerMove={(e) => handlePointer(e, false)}
        onPointerLeave={() => setHover(null)}
        onPointerDown={(e) => {
          if (e.button !== 0) return;
          handlePointer(e, true);
        }}
        style={{ cursor: interactive && hover ? 'pointer' : interactive ? 'default' : 'default' }}
      >
        {/* ---- iso groundwork: ground shadow + extruded walls ---- */}
        {iso && isoFloor && (
          <g pointerEvents="none">
            <polygon
              points={isoFloor.map((p) => `${p.x},${p.y}`).join(' ')}
              fill="var(--od-canvas)"
              stroke="none"
              opacity={0}
            />
            {/* raised slab shadow */}
            <polygon
              points={isoFloor.map((p) => `${p.x},${p.y + wallPx}`).join(' ')}
              fill="rgba(0,0,0,0.10)"
            />
            {/* side walls: quad per floor edge extruded straight down-screen */}
            {[0, 1, 2, 3].map((i) => {
              const a = isoFloor[i];
              const b = isoFloor[(i + 1) % 4];
              return (
                <polygon
                  key={i}
                  points={`${a.x},${a.y} ${b.x},${b.y} ${b.x},${b.y + wallPx} ${a.x},${a.y + wallPx}`}
                  fill={i === 1 || i === 2 ? 'var(--od-slab-front)' : 'var(--od-slab-side)'}
                  stroke="var(--od-line)"
                  strokeWidth={m / 480}
                />
              );
            })}
            {/* site datum grid beyond the slab */}
            <g stroke="var(--od-line)" strokeOpacity={0.25} strokeWidth={m / 640}>
              {[-1, 0, 1, 2, 3, 4].map((gx) => (
                <line
                  key={`gx${gx}`}
                  x1={toIso(gx * (W / 2), 0).x + isoTransform.tx}
                  y1={toIso(gx * (W / 2), 0).y + isoTransform.ty - wallPx * 0.5}
                  x2={toIso(gx * (W / 2), H).x + isoTransform.tx}
                  y2={toIso(gx * (W / 2), H).y + isoTransform.ty + wallPx * 0.5}
                />
              ))}
              {[-1, 0, 1, 2, 3, 4].map((gy) => (
                <line
                  key={`gy${gy}`}
                  x1={toIso(0, gy * (H / 2)).x + isoTransform.tx}
                  y1={toIso(0, gy * (H / 2)).y + isoTransform.ty - wallPx * 0.5}
                  x2={toIso(W, gy * (H / 2)).x + isoTransform.tx}
                  y2={toIso(W, gy * (H / 2)).y + isoTransform.ty + wallPx * 0.5}
                />
              ))}
            </g>
          </g>
        )}

        {/* ---- external environment overlay (plan view) ---- */}
        {!iso && scope !== 'venue' && environment && (() => {
          const roadWidth = (kind: string) =>
            kind === 'ARTERIAL' ? m / 20 : kind === 'RING' ? m / 24 : kind === 'MAJOR' ? m / 28 : kind === 'ACCESS' ? m / 40 : m / 34;
          return (
            <g pointerEvents="none">
              {/* road casing + fill, coloured by live external congestion */}
              {environment.roads.map((r) => {
                if (r.points.length < 2) return null;
                const st = extState.get(r.id);
                const d = `M${r.points.map((p) => `${p.x} ${p.y}`).join(' L')}`;
                const fill = st && st.congestion > 0 ? elementColor(st.risk as never, st.congestion) : 'var(--od-line)';
                return (
                  <g key={r.id}>
                    <path d={d} fill="none" stroke="var(--od-canvas)" strokeWidth={roadWidth(r.kind) + m / 140} strokeLinejoin="round" strokeLinecap="round" />
                    <path d={d} fill="none" stroke={fill} strokeWidth={roadWidth(r.kind)} strokeLinejoin="round" strokeLinecap="round" strokeOpacity={st && st.congestion > 0 ? 0.95 : 0.75} strokeDasharray={r.kind === 'ACCESS' ? 'none' : undefined} />
                    {r.name && r.kind !== 'ACCESS' && (
                      <text x={r.points[Math.floor(r.points.length / 2)].x} y={r.points[Math.floor(r.points.length / 2)].y - m / 60} textAnchor="middle" fontSize={Math.max(6, m / 80)} fill="var(--od-muted)" letterSpacing="0.08em">
                        {r.name}
                      </text>
                    )}
                  </g>
                );
              })}
              {/* junctions */}
              {environment.junctions.map((j) => {
                const st = extState.get(j.id);
                const fill = st && st.congestion > 0 ? elementColor(st.risk as never, st.congestion) : 'var(--od-line-strong)';
                return (
                  <g key={j.id}>
                    <rect x={j.position.x - m / 90} y={j.position.y - m / 90} width={m / 45} height={m / 45} fill="var(--od-surface)" stroke={fill} strokeWidth={m / 220} transform={`rotate(45 ${j.position.x} ${j.position.y})`} />
                    {j.name && (
                      <text x={j.position.x + m / 36} y={j.position.y + m / 90} fontSize={Math.max(6, m / 85)} fill="var(--od-muted)" letterSpacing="0.06em">
                        {j.name}
                      </text>
                    )}
                  </g>
                );
              })}
              {/* transit stops */}
              {environment.transit.map((t) => (
                <g key={t.id}>
                  <rect x={t.position.x - m / 60} y={t.position.y - m / 60} width={m / 30} height={m / 30} fill="var(--od-surface)" stroke="var(--od-line-strong)" strokeWidth={m / 260} />
                  <text x={t.position.x} y={t.position.y + m / 55} textAnchor="middle" fontSize={Math.max(6, m / 60)} fontWeight={800} fill="var(--od-soft)">
                    {t.kind === 'RAIL' ? 'R' : t.kind === 'TRAM' ? 'T' : 'B'}
                  </text>
                  <text x={t.position.x} y={t.position.y + m / 28} textAnchor="middle" fontSize={Math.max(6, m / 85)} fill="var(--od-muted)" letterSpacing="0.06em">
                    {t.name}
                  </text>
                </g>
              ))}
              {/* parking */}
              {environment.parking.map((p) => (
                <g key={p.id}>
                  <rect x={p.position.x - m / 40} y={p.position.y - m / 40} width={m / 20} height={m / 20} fill="var(--od-surface)" stroke="var(--od-line-strong)" strokeWidth={m / 240} />
                  <text x={p.position.x} y={p.position.y + m / 34} textAnchor="middle" fontSize={Math.max(7, m / 46)} fontWeight={800} fill="var(--od-soft)">
                    P
                  </text>
                  <text x={p.position.x} y={p.position.y + m / 16} textAnchor="middle" fontSize={Math.max(6, m / 85)} fill="var(--od-muted)" letterSpacing="0.06em">
                    {p.capacity} bays
                  </text>
                </g>
              ))}
              {/* attribution */}
              <text x={scopeBox?.minX ?? m / 40} y={(scopeBox?.maxY ?? H) + m / 34} fontSize={Math.max(6, m / 90)} fill="var(--od-muted)" letterSpacing="0.08em">
                {environment.source === 'LIVE_OSM' ? 'Roads © OpenStreetMap contributors (ODbL)' : 'Bundled offline road network'}
              </text>
            </g>
          );
        })()}

        <g transform={isoTransform.matrix || undefined}>
          {!iso && (
            <>
              <rect x="0" y="0" width={W} height={H} fill="var(--od-canvas)" />
              <rect x="0" y="0" width={W} height={H} fill="none" stroke="var(--od-line)" strokeWidth={m / 500} opacity={0.8} />
            </>
          )}
          {iso && (
            <>
              {/* floor plate */}
              <rect x="0" y="0" width={W} height={H} fill="var(--od-slab-top)" stroke="var(--od-line)" strokeWidth={m / 480} />
              {/* diamond grid on the floor */}
              <g stroke="var(--od-line)" strokeOpacity={0.28} strokeWidth={m / 620}>
                {Array.from({ length: Math.ceil(W / 50) + 1 }, (_, i) => i * 50).map((gx) => (
                  <line key={`fx${gx}`} x1={gx} y1={0} x2={gx} y2={H} />
                ))}
                {Array.from({ length: Math.ceil(H / 50) + 1 }, (_, i) => i * 50).map((gy) => (
                  <line key={`fy${gy}`} x1={0} y1={gy} x2={W} y2={gy} />
                ))}
              </g>
            </>
          )}

          {/* edges */}
          {drawnEdges.map((ed) => {
            if (!ed) return null;

            // Active REDIRECT intervention on this edge (Req 6 / Task 10)
            const isRedirectActive = !!(sim?.interventions_applied.some(
              (i) =>
                i.type === 'REDIRECT' &&
                ((i.parameters.from === ed.e.source && i.parameters.to === ed.e.destination) ||
                  (i.parameters.edge_id === ed.key) ||
                  (i.parameters.from === ed.e.source)),
            ));

            // Newly-opened OPEN_CORRIDOR on this edge — framer-motion entrance (Req 6 / Task 10)
            const isOpenCorridor = !!(
              ed.e.is_open &&
              sim?.interventions_applied.some(
                (i) =>
                  i.type === 'OPEN_CORRIDOR' &&
                  ((i.parameters.edge_id === ed.key) ||
                    (i.parameters.from === ed.e.source && i.parameters.to === ed.e.destination)),
              )
            );

            const lineEl = (
              <line
                x1={ed.s.x} y1={ed.s.y} x2={ed.d.x} y2={ed.d.y}
                stroke={ed.stroke} strokeWidth={ed.width} opacity={ed.opacity}
                strokeDasharray={ed.dash}
                className={isRedirectActive ? 'od-redirect-active' : undefined}
              />
            );

            return (
              <g key={ed.key}>
                {isOpenCorridor ? (
                  <motion.g
                    initial={{ opacity: 0, scale: 0.6 }}
                    animate={{ opacity: 1, scale: 1 }}
                    style={{ transformOrigin: `${ed.mid.x}px ${ed.mid.y}px` }}
                  >
                    {lineEl}
                  </motion.g>
                ) : (
                  lineEl
                )}
                {ed.closedDraft && (
                  <g>
                    <text x={ed.mid.x} y={ed.mid.y - nodeR * 0.7} textAnchor="middle" fontSize={Math.max(7, m / 58)} fill="var(--od-danger)" fontWeight={800} letterSpacing="0.08em">
                      CLOSED
                    </text>
                  </g>
                )}
                {ed.hot && (
                  <g pointerEvents="none">
                    <circle cx={ed.mid.x} cy={ed.mid.y} r={nodeR * 1.1} fill="none" stroke="var(--od-warn)" strokeWidth={m / 240} className="od-pulse" />
                    <text x={ed.mid.x} y={ed.mid.y - nodeR * 0.9} textAnchor="middle" fontSize={Math.max(7, m / 56)} fontWeight={800} letterSpacing="0.1em" fill="var(--od-warn)">
                      BOTTLENECK
                    </text>
                  </g>
                )}
              </g>
            );
          })}

          {/* redirect draft */}
          {drafts?.redirect && (() => {
            const s = pos.get(drafts.redirect.from);
            const d = pos.get(drafts.redirect.to);
            if (!s || !d) return null;
            const ang = Math.atan2(d.y - s.y, d.x - s.x);
            const ax = d.x - Math.cos(ang) * nodeR * 1.4;
            const ay = d.y - Math.sin(ang) * nodeR * 1.4;
            const mid = { x: (s.x + d.x) / 2, y: (s.y + d.y) / 2 - nodeR * 1.6 };
            return (
              <g pointerEvents="none">
                <line x1={s.x} y1={s.y} x2={d.x} y2={d.y} stroke="var(--od-warn)" strokeWidth={m / 170} strokeDasharray="4 4" opacity={0.95} />
                <polygon
                  points={`${ax},${ay} ${ax - Math.cos(ang - Math.PI / 4) * nodeR * 0.55},${ay - Math.sin(ang - Math.PI / 4) * nodeR * 0.55} ${ax - Math.cos(ang + Math.PI / 4) * nodeR * 0.55},${ay - Math.sin(ang + Math.PI / 4) * nodeR * 0.55}`}
                  fill="var(--od-warn)"
                />
                <text x={mid.x} y={mid.y} textAnchor="middle" fontSize={Math.max(7, m / 56)} fontWeight={800} fill="var(--od-warn)" letterSpacing="0.08em">
                  REDIRECT {drafts.redirect.pct}%
                </text>
              </g>
            );
          })()}

          {/* nodes */}
          {venue.nodes.map((n) => {
            const p = pos.get(n.id);
            if (!p) return null;
            const st = nodeState.get(n.id);
            const r = n.type === 'ZONE' ? nodeR * 1.8 : n.type === 'CONCESSION' ? nodeR * 1.1 : nodeR;
            const sel = selectedNode === n.id;
            const hov = hover?.kind === 'node' && hover.id === n.id;
            const uri = riskColoring && st && st.risk !== 'NORMAL';
            const stroke = sel
              ? 'var(--od-ok)'
              : uri
                ? elementColor(st!.risk, st!.utilisation)
                : hov
                  ? 'var(--od-ink)'
                  : 'var(--od-ink)';
            const strokeW = sel ? m / 150 : m / 400;
            const fill =
              n.type === 'EMERGENCY_EXIT'
                ? 'var(--od-emergency)'
                : sel
                  ? 'transparent'
                  : 'var(--od-surface)';
            const label = NODE_KIND[n.type] ?? n.type;
            return (
              <g key={n.id} transform={`translate(${p.x},${p.y})`}>
                {uri && (
                  <circle r={r * 1.7} fill="none" stroke={elementColor(st!.risk, st!.utilisation)} strokeWidth={m / 300} opacity={0.55} />
                )}
                {n.type === 'ENTRY' && (
                  <g>
                    <rect x={-r} y={-r} width={r * 2} height={r * 2} fill={fill} stroke={stroke} strokeWidth={strokeW} />
                    <line x1={-r} y1={-r * 0.55} x2={r} y2={-r * 0.55} stroke={stroke} strokeWidth={m / 320} />
                  </g>
                )}
                {n.type === 'EXIT' && (
                  <path d={`M${-r},${-r} L${r},0 L${-r},${r} Z`} fill={fill} stroke={stroke} strokeWidth={strokeW} strokeLinejoin="miter" />
                )}
                {n.type === 'EMERGENCY_EXIT' && (
                  <g>
                    <path d={`M0,${-r} L${r},0 L0,${r} L${-r},0 Z`} fill={fill} stroke={stroke} strokeWidth={Math.max(strokeW, m / 340)} />
                    <line x1={-r * 0.5} y1={0} x2={r * 0.5} y2={0} stroke={stroke} strokeWidth={m / 340} />
                  </g>
                )}
                {n.type === 'CONCESSION' && (
                  <path
                    d={[
                      `M0,${-r}`, `L${r * 0.866},${-r * 0.5}`, `L${r * 0.866},${r * 0.5}`, `L0,${r}`,
                      `L${-r * 0.866},${r * 0.5}`, `L${-r * 0.866},${-r * 0.5}`, 'Z',
                    ].join(' ')}
                    fill={fill}
                    stroke={stroke}
                    strokeWidth={strokeW}
                  />
                )}
                {n.type === 'CHECKPOINT' && (
                  <g>
                    <circle r={r} fill={fill} stroke={stroke} strokeWidth={strokeW} />
                    <line x1={-r * 0.6} y1={-r * 0.6} x2={r * 0.6} y2={r * 0.6} stroke={stroke} strokeWidth={m / 360} />
                  </g>
                )}
                {n.type === 'INTERSECTION' && (
                  <rect x={-r * 0.55} y={-r * 0.55} width={r * 1.1} height={r * 1.1} fill={fill} stroke={stroke} strokeWidth={strokeW} />
                )}
                {n.type === 'ZONE' && (
                  <rect x={-r * 0.8} y={-r * 0.8} width={r * 1.6} height={r * 1.6} fill={fill} stroke={stroke} strokeWidth={strokeW} />
                )}

                {sel && <circle r={r * 1.5} fill="none" stroke="var(--od-ok)" strokeWidth={m / 240} />}

                {showLabels && !iso && (
                  <text y={r + nodeR * 1.1} textAnchor="middle" fontSize={Math.max(6.5, nodeR * 0.42)} fill="var(--od-muted)" letterSpacing="0.1em" style={{ textTransform: 'uppercase' }}>
                    {n.id.replace(/_/g, ' ')}
                  </text>
                )}
                {showLabels && !iso && (n.type === 'ENTRY' || n.type === 'EXIT' || n.type === 'EMERGENCY_EXIT') && (
                  <text y={-r - nodeR * 0.7} textAnchor="middle" fontSize={Math.max(6, nodeR * 0.4)} fill="var(--od-muted)" letterSpacing="0.14em">
                    {label}
                  </text>
                )}
              </g>
            );
          })}

          {/* agents — SVG fallback only when Canvas 2D is unavailable (Req 19) */}
          {!canvasSupported &&
            showAgents &&
            sim &&
            sim.agents.map((a) => {
              const r = a.is_rerouted ? Math.max(1.6, nodeR * 0.24) : Math.max(1.4, nodeR * 0.2);
              return (
                <g key={a.id} className="agent-dot" transform={`translate(${a.position.x.toFixed(1)},${a.position.y.toFixed(1)})`}>
                  {iso && agentShadowOffset > 0 && (
                    <ellipse
                      cx={agentShadowOffset}
                      cy={agentShadowOffset}
                      rx={r * 0.9}
                      ry={r * 0.45}
                      fill="#000"
                      opacity={0.16}
                    />
                  )}
                  <circle
                    r={r}
                    fill={a.is_emergency ? 'var(--od-emergency)' : a.is_rerouted ? 'var(--od-warn)' : 'var(--od-ink)'}
                    fillOpacity={a.is_emergency ? 1 : 0.75}
                  />
                </g>
              );
            })}

          {/* emergency state */}
          {sim?.emergency_active && (
            <g pointerEvents="none">
              <rect x="0" y="0" width={W} height={H} fill="none" stroke="var(--od-danger)" strokeWidth={m / 200} opacity={0.7} />
              <rect x="0" y="0" width={W} height={H} fill="var(--od-danger)" opacity={0.05} />
              <text x={nodeR * 1.6} y={nodeR * 1.6} fontSize={Math.max(8, m / 46)} fontWeight={800} fill="var(--od-danger)" letterSpacing="0.14em">
                EVACUATION
              </text>
            </g>
          )}

          {/* incident hazard zone */}
          {sim?.incident && sim.hazard_zones?.[0] && (() => {
            const zone = sim.hazard_zones[0];
            const loc = zone.location ? pos.get(zone.location) : null;
            if (!loc) return null;
            const r = Math.max(nodeR, zone.radius_m);
            const spread = sim.incident!.spread_rate_m_min > 0;
            return (
              <g pointerEvents="none">
                <circle cx={loc.x} cy={loc.y} r={r} fill="var(--od-danger)" opacity={0.09} />
                <circle cx={loc.x} cy={loc.y} r={r} fill="none" stroke="var(--od-danger)" strokeWidth={m / 260} strokeDasharray={spread ? '10 6' : undefined} className={spread ? 'od-pulse' : undefined} />
                <circle cx={loc.x} cy={loc.y} r={Math.min(nodeR * 1.6, r)} fill="var(--od-danger)" opacity={0.35} className="od-pulse" />
                <text x={loc.x} y={loc.y - r - nodeR * 1.2} textAnchor="middle" fontSize={Math.max(8, m / 52)} fontWeight={800} fill="var(--od-danger)" letterSpacing="0.12em">
                  {sim.incident.type} ZONE{spread ? ' · SPREADING' : ''}
                </text>
              </g>
            );
          })()}
        </g>

        {/* ---- iso upright label overlay ---- */}
        {iso && showLabels && (
          <g pointerEvents="none">
            {venue.nodes.map((n) => {
              const p = proj.get(n.id);
              if (!p) return null;
              const r = n.type === 'ZONE' ? nodeR * 1.8 : n.type === 'CONCESSION' ? nodeR * 1.1 : nodeR;
              const label = NODE_KIND[n.type] ?? n.type;
              return (
                <g key={n.id}>
                  <text x={p.x} y={p.y + r + nodeR * 1.1} textAnchor="middle" fontSize={Math.max(6.5, nodeR * 0.42)} fill="var(--od-muted)" letterSpacing="0.1em" style={{ textTransform: 'uppercase' }}>
                    {n.id.replace(/_/g, ' ')}
                  </text>
                  {(n.type === 'ENTRY' || n.type === 'EXIT' || n.type === 'EMERGENCY_EXIT') && (
                    <text x={p.x} y={p.y - r - nodeR * 0.7} textAnchor="middle" fontSize={Math.max(6, nodeR * 0.4)} fill="var(--od-muted)" letterSpacing="0.14em">
                      {label}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        )}
      </svg>

      {/* ---- Canvas / SVG overlay layers (Z-1 … Z-4) ---- */}

      {/* Z-1: Density heatmap — visible when viewMode === 'density' | 'crowd' */}
      <DensityGridLayer
        agents={sim?.agents ?? null}
        venue={venue}
        visible={viewMode === 'density' || viewMode === 'crowd'}
      />

      {/* Z-2: Canvas 2D agent layer — skipped when Canvas 2D is unavailable (SVG fallback above) */}
      {canvasSupported && simRef && (
        <InstrumentCanvasAgents
          simRef={simRef}
          venue={venue}
          showAgents={showAgents}
          viewBoxX={0}
          viewBoxY={0}
          viewBoxW={W}
          viewBoxH={H}
          onCanvasUnsupported={() => setCanvasSupported(false)}
        />
      )}

      {/* Z-3: Flow direction arrows */}
      <FlowArrowLayer
        sim={sim}
        venue={venue}
        nodePositions={pos}
        viewBox={activeViewBox}
      />

      {/* Z-4: Bottleneck pulse rings */}
      <BottleneckPulseLayer
        bottlenecks={sim?.bottlenecks ?? []}
        venue={venue}
        nodePositions={pos}
        viewBox={activeViewBox}
      />

      {/* spatial action ring — the world is the interface */}
      {mode === 'intervene' && interactive && selected && ring && (() => {
        const node = selected.kind === 'node' ? venue?.nodes.find((n) => n.id === selected.id) ?? null : null;
        const edge =
          selected.kind === 'edge' ? venue?.edges.find((e) => edgeKey(e.source, e.destination) === selected.id) ?? null : null;

        const isGate = node?.type === 'ENTRY';
        const isExit = node?.type === 'EXIT' || node?.type === 'EMERGENCY_EXIT';
        const incidentEdges = node
          ? venue?.edges.filter((e) => e.source === node.id || e.destination === node.id).map((e) => edgeKey(e.source, e.destination)) ?? []
          : [];
        const gateClosed = incidentEdges.length > 0 && incidentEdges.every((k) => drafts?.closedEdgeIds.includes(k) ?? false);

        const ringActions: { label: string; tone?: 'danger' | 'ok' | 'warn'; act: () => void; disabled?: boolean }[] = [];

        if (isGate || isExit) {
          ringActions.push({
            label: gateClosed ? 'OPEN GATE' : 'CLOSE GATE',
            tone: gateClosed ? 'ok' : 'danger',
            disabled: incidentEdges.length === 0,
            act: () => {
              if (gateClosed) onSpatialAction?.({ type: 'open', selection: selected });
              else onSpatialAction?.({ type: 'close', selection: selected });
            },
          });
        }
        if (isGate) {
          ringActions.push({
            label: 'REDIRECT',
            act: () => onSpatialAction?.({ type: 'redirect', selection: selected }),
          });
        }
        if (selected.kind === 'edge' && edge) {
          const closedDraft = drafts?.closedEdgeIds.includes(selected.id) ?? false;
          ringActions.push({
            label: closedDraft ? 'OPEN CORRIDOR' : 'CLOSE CORRIDOR',
            tone: closedDraft ? 'ok' : 'danger',
            act: () =>
              onSpatialAction?.(
                closedDraft ? { type: 'open', selection: selected } : { type: 'close', selection: selected },
              ),
          });
        }
        ringActions.push({
          label: 'INCIDENT',
          tone: 'warn',
          act: () => onSpatialAction?.({ type: 'incident', selection: selected }),
        });

        const boxW = 150;
        const rows = ringActions.length;
        const left = Math.min(Math.max(6, ring.x + 14), (rootRef.current?.clientWidth ?? 600) - boxW - 6);
        const top = Math.min(Math.max(6, ring.y - rows * 18), (rootRef.current?.clientHeight ?? 400) - rows * 30 - 6);
        return (
          <div
            className="absolute z-20 border border-od-line bg-od-panel shadow-sm"
            style={{ left, top, width: boxW }}
            onPointerDown={(e) => e.stopPropagation()}
            role="group"
            aria-label={`Actions for ${selected.id}`}
          >
            <div className="flex items-center justify-between border-b border-od-line px-2 py-1">
              <span className="truncate text-[9px] uppercase tracking-[0.14em] text-od-ink font-bold">
                {node ? node.id.replace(/_/g, ' ') : edge?.id.replace(/_/g, ' ') ?? selected.id}
              </span>
              <button
                className="cursor-pointer text-od-muted hover:text-od-ink px-0.5"
                onClick={() => onSelect?.(null)}
                aria-label="Close actions"
              >
                ✕
              </button>
            </div>
            <div className="p-1 space-y-1">
              {ringActions.map((a) => (
                <button
                  key={a.label}
                  disabled={a.disabled}
                  onClick={a.act}
                  className={`btn w-full ${
                    a.tone === 'danger' ? 'btn-danger' : a.tone === 'ok' ? 'btn-ok' : a.tone === 'warn' ? 'btn-solid' : 'btn-ghost'
                  }`}
                >
                  {a.label}
                </button>
              ))}
            </div>
          </div>
        );
      })()}

      {/* projection toggle */}
      {interactive && (
        <div
          className="absolute top-2 right-2 z-10 flex items-center border border-od-line bg-od-panel"
          onPointerDown={(e) => e.stopPropagation()}
        >
          {environment && onScope && (
            <>
              {(
                [
                  { id: 'venue', label: 'VENUE' },
                  { id: 'surround', label: 'SURROUND' },
                  { id: 'network', label: 'NETWORK' },
                ] as { id: CanvasScope; label: string }[]
              ).map((v) => (
                <button
                  key={v.id}
                  onClick={() => onScope(v.id)}
                  disabled={iso && v.id !== 'venue'}
                  title={iso ? 'Switch to PLAN to pan the surroundings' : undefined}
                  className={`px-2 py-1 text-[9px] uppercase tracking-[0.14em] font-bold cursor-pointer border-r border-od-line last:border-r-0 disabled:opacity-40 disabled:cursor-not-allowed ${
                    scope === v.id && !iso ? 'bg-od-ink text-od-canvas' : 'text-od-muted hover:text-od-ink'
                  }`}
                >
                  {v.label}
                </button>
              ))}
              <button
                onClick={onRefreshEnvironment}
                title="Reload surroundings (live OpenStreetMap when configured)"
                className="flex items-center gap-1 px-2 py-1 text-[9px] uppercase tracking-[0.14em] font-bold cursor-pointer text-od-muted hover:text-od-ink border-r border-od-line last:border-r-0"
              >
                <RefreshCw className="w-3 h-3" />
              </button>
            </>
          )}
          {(
            [
              { id: 'plan', label: 'PLAN', icon: PanelsTopLeft },
              { id: 'iso', label: '2.5D', icon: Boxes },
            ] as const
          ).map((v) => (
            <button
              key={v.id}
              onClick={() => setIso(v.id === 'iso')}
              className={`flex items-center gap-1 px-2 py-1 text-[9px] uppercase tracking-[0.14em] font-bold cursor-pointer border-r border-od-line last:border-r-0 ${
                (v.id === 'iso') === iso ? 'bg-od-ink text-od-canvas' : 'text-od-muted hover:text-od-ink'
              }`}
            >
              <v.icon className="w-3 h-3" />
              {v.label}
            </button>
          ))}
        </div>
      )}

      {/* legend */}
      {sim && (
        <div className="absolute bottom-2 left-2 flex flex-wrap items-center gap-x-3 gap-y-1 px-2 py-1 bg-od-panel text-[9px] uppercase tracking-[0.14em] text-od-muted">
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-od-ink" /> agent
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-od-emergency" /> emergency
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-[3px] bg-od-warn" /> elevated
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-[3px] bg-od-danger" /> critical
          </span>
          {sim.incident && (
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-od-danger od-pulse" /> {sim.incident.type.toLowerCase()} zone
            </span>
          )}
        </div>
      )}
    </div>
  );
}
