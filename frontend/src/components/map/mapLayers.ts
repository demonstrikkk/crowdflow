import { GeoJsonLayer, IconLayer, PolygonLayer, ScatterplotLayer } from '@deck.gl/layers';
import { TripsLayer } from '@deck.gl/geo-layers';
import type { Layer } from '@deck.gl/core';
import type { GeoProjector } from '../../lib/geoProjection';
import { venueGeoFootprint } from '../../lib/geoProjection';
import type {
  ExternalEnvironment,
  ExternalElementState,
  SimulationState,
  VenueModel,
  WorldEdgeState,
  WorldGraph,
  WorldState,
} from '../../lib/types';

// --------------------------------------------------------------------------- //
//  Deck.gl layer builder for the map-centric CrowdFlow workspace.
//
//  Everything rendered here is derived from real backend state (sim.world /
//  sim.external / sim.bottlenecks): edge risk, gate queues, demand sources,
//  predictions, and animated per-mode flows. No fabricated counts.
//
//  Two-phase build for performance:
//    * ``buildStaticLayers`` — layer instances memoized on state; only rebuilt
//      when the sim/world actually changes.
//    * ``buildTripRows`` + ``buildTripLayers`` — animated per-mode trips. The
//      *rows* are memoized on state; only the four TripsLayer instances are
//      rebuilt each animation frame (stable data → deck just moves the clock).
// --------------------------------------------------------------------------- //

export interface TipRow {
  k: string;
  v: string;
  c?: string;
}

export interface Tip {
  title: string;
  rows: TipRow[];
  note?: string;
}

const LOOP_S = 60; // animation loop length (seconds)

// ── colors ─────────────────────────────────────────────────────────────────
const RGBA = (hex: string, a = 255): [number, number, number, number] => {
  const h = hex.replace('#', '');
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
    a,
  ];
};

export const WORLD_ROAD = RGBA('#8a93a0');
export const WORLD_FOOTPATH = RGBA('#b0b8c2');
export const REROUTE_COLOR = RGBA('#8d6be8');
export const CLOSED_COLOR = RGBA('#4a4f57');

const MODE_COLOR: Record<string, [number, number, number, number]> = {
  walk: RGBA('#2dd4bf', 200),
  car: RGBA('#fb923c', 235),
  bus: RGBA('#3b82f6', 240),
  metro: RGBA('#a855f7', 245),
};

const SOURCE_MODE_COLOR: Record<string, [number, number, number, number]> = {
  METRO: RGBA('#a855f7'),
  BUS: RGBA('#3b82f6'),
  PARKING: RGBA('#fb923c'),
  DROP_OFF: RGBA('#fb923c'),
  WALKING: RGBA('#2dd4bf'),
  GATHERING: RGBA('#2dd4bf'),
};

// stylized particle speeds so each mode reads distinctly (visual pacing only —
// the *counts* come from real flow_by_mode, speeds are cosmetic)
const MODE_SPEED_MPS: Record<string, number> = {
  walk: 1.8,
  car: 13,
  bus: 9,
  metro: 7,
};

export function riskRgba(risk: string): [number, number, number, number] {
  if (risk === 'CRITICAL' || risk === 'HIGH') return RGBA('#ef4444');
  if (risk === 'ELEVATED') return RGBA('#f59e0b');
  return RGBA('#10b981');
}

function riskToHex(risk: string): string {
  if (risk === 'CRITICAL' || risk === 'HIGH') return '#ef4444';
  if (risk === 'ELEVATED') return '#f59e0b';
  return '#10b981';
}

// ── projector helper (venue local metres → [lng, lat]) ─────────────────────
function toLngLat(p: GeoProjector, pt: { x: number; y: number }): [number, number] {
  const [lat, lng] = p.toLatLng(pt.x, pt.y);
  return [lng, lat];
}

// ── inline SVG icons (auto-packed by IconLayer; mask silhouettes are tinted) ─
const svg = (inner: string) =>
  'data:image/svg+xml;base64,' +
  btoa(
    `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">${inner}</svg>`,
  );

interface IconDef {
  url: string;
  width: number;
  height: number;
  mask: boolean;
}

const ICONS: Record<string, IconDef> = {
  gate: { url: svg('<rect x="2" y="3" width="20" height="18" fill="#000"/><rect x="8" y="3" width="3" height="18" fill="#fff"/><rect x="13" y="3" width="3" height="18" fill="#fff"/>'), width: 22, height: 22, mask: true },
  exit: { url: svg('<path d="M4 12h12M11 6l6 6-6 6" fill="none" stroke="#000" stroke-width="3"/>'), width: 22, height: 22, mask: true },
  emergency: { url: svg('<path d="M12 2 2 22h20Z" fill="#000"/>'), width: 22, height: 22, mask: true },
  metro: { url: svg('<rect x="3" y="5" width="18" height="14" rx="2" fill="#000"/><text x="12" y="16" font-size="10" text-anchor="middle" fill="#fff" font-family="Arial" font-weight="bold">M</text>'), width: 24, height: 24, mask: true },
  bus: { url: svg('<rect x="2" y="3" width="20" height="18" rx="2" fill="#000"/><rect x="5" y="7" width="14" height="5" fill="#fff"/><circle cx="7" cy="20" r="1.6" fill="#fff"/><circle cx="17" cy="20" r="1.6" fill="#fff"/>'), width: 24, height: 24, mask: true },
  car: { url: svg('<rect x="3" y="9" width="18" height="6" rx="2" fill="#000"/><path d="M5 9 7 5h10l2 4z" fill="#000"/><circle cx="7" cy="16" r="2.2" fill="#fff"/><circle cx="17" cy="16" r="2.2" fill="#fff"/>'), width: 24, height: 24, mask: true },
  walk: { url: svg('<circle cx="12" cy="5" r="3" fill="#000"/><path d="M12 8c-3 1-4 5-5 9h3l1-4 2 1 1 3h3c-1-4-2-8-5-9z" fill="#000"/>'), width: 24, height: 24, mask: true },
};

function edgeTip(e: WorldGraph['edges'][number], live?: WorldEdgeState): Tip {
  const rows: TipRow[] = [
    { k: 'class', v: `${e.kind} · ${Math.round(e.length_m)} m` },
  ];
  if (live) {
    rows.push({ k: 'risk', v: live.risk, c: riskToHex(live.risk) });
    rows.push({ k: 'flow', v: `${live.flow_per_min.toFixed(1)}/min` });
    rows.push({ k: 'people', v: String(live.people) });
    if (live.time_to_critical_min != null) {
      rows.push({ k: 'to critical', v: `~${live.time_to_critical_min.toFixed(1)} min` });
    }
    if (live.closed) rows.push({ k: 'state', v: 'CLOSED', c: '#ef4444' });
    if (live.rerouted) rows.push({ k: 'state', v: 'REROUTED', c: '#8d6be8' });
  } else {
    rows.push({ k: 'cap', v: `${Math.round(e.capacity_estimate)}/h · est` });
  }
  return { title: e.id.replace(/_/g, ' '), rows };
}

// ── animated trip rows (memoized on state) ─────────────────────────────────
export type TripRows = Record<string, { path: [number, number][]; timestamps: number[] }[]>;

export function buildTripRows(
  world: WorldGraph,
  state: WorldState | null,
  p: GeoProjector,
): TripRows {
  const modes = ['walk', 'car', 'bus', 'metro'];
  const out: TripRows = { walk: [], car: [], bus: [], metro: [] };
  const scale: Record<string, number> = { walk: 0.05, car: 0.9, bus: 3, metro: 6 };
  const max: Record<string, number> = { walk: 14, car: 6, bus: 2, metro: 2 };

  for (const mode of modes) {
    const rows = out[mode];
    for (const e of world.edges) {
      const flow = state?.edges[e.id]?.flow_by_mode?.[mode] ?? 0;
      if (flow <= 0 || e.geometry.length < 2) continue;
      const lenM = Math.max(e.length_m, 10);
      const count = Math.min(max[mode], Math.max(0, Math.round(flow * scale[mode])));
      if (count === 0) continue;
      const path = e.geometry.map((pt) => toLngLat(p, pt));
      const dur = Math.max(1.5, Math.min(LOOP_S * 0.9, (lenM / MODE_SPEED_MPS[mode]) * 2.4));
      for (let i = 0; i < count; i += 1) {
        let h = 0;
        const seedKey = `${e.id}:${mode}:${i}`;
        for (const c of seedKey) h = (h * 31 + c.charCodeAt(0)) % 9973;
        const start = (h / 9973) * LOOP_S;
        rows.push({
          path,
          timestamps: [start, Math.min(start + dur, LOOP_S - 0.05)],
        });
      }
    }
  }
  return out;
}

const TRIP_OPTS: Record<string, { width: number; trail: number }> = {
  walk: { width: 2.5, trail: 0.35 },
  car: { width: 4.5, trail: 0.55 },
  bus: { width: 6.5, trail: 0.65 },
  metro: { width: 8, trail: 0.7 },
};

export function buildTripLayers(rows: TripRows, time: number): Layer[] {
  const layers: Layer[] = [];
  for (const mode of ['walk', 'car', 'bus', 'metro'] as const) {
    const opts = TRIP_OPTS[mode];
    layers.push(
      new TripsLayer({
        id: `trips-${mode}`,
        data: rows[mode],
        getPath: (d) => d.path,
        getTimestamps: (d) => d.timestamps,
        getColor: () => MODE_COLOR[mode],
        getWidth: opts.width,
        widthMinPixels: 1.5,
        widthMaxPixels: 6,
        currentTime: time % LOOP_S,
        loopLength: LOOP_S,
        fadeTrail: true,
        trailLength: opts.trail,
      }),
    );
  }
  return layers;
}

// ── static layers (memoized on state) ──────────────────────────────────────
export interface MapLayerContext {
  venue: VenueModel;
  env: ExternalEnvironment | null;
  world: WorldGraph | null;
  sim: SimulationState | null;
  state: WorldState | null;
  externalState: ExternalElementState[];
  showLive: boolean;
  projector: GeoProjector;
}

function worldLayers(world: WorldGraph, state: WorldState | null, p: GeoProjector): Layer[] {
  const layers: Layer[] = [];

  // edges: base stroke coloured by live risk / closed / rerouted
  const features = world.edges
    .filter((e) => e.geometry.length >= 2)
    .map((e) => {
      const live = state?.edges[e.id];
      return {
        type: 'Feature' as const,
        properties: { e, live, tip: edgeTip(e, live), tipKey: `e:${e.id}` },
        geometry: {
          type: 'LineString' as const,
          coordinates: e.geometry.map((pt) => toLngLat(p, pt)),
        },
      };
    });

  layers.push(
    new GeoJsonLayer({
      id: 'world-edges',
      data: { type: 'FeatureCollection', features } ,
      pickable: true,
      getLineColor: (f: any) => {
        const { e, live } = f.properties;
        if (live?.closed) return CLOSED_COLOR;
        if (live?.rerouted) return REROUTE_COLOR;
        if (live && live.risk !== 'NORMAL') return riskRgba(live.risk);
        return e.kind === 'FOOTPATH' || e.kind === 'GATE_LINK' ? WORLD_FOOTPATH : WORLD_ROAD;
      },
      getLineWidth: (f: any) => {
        const live = f.properties.live;
        return live ? Math.min(9, 2.5 + Math.round((live.flow_per_min || 0) / 50)) : 2.2;
      },
      lineWidthUnits: 'pixels',
      lineWidthMinPixels: 1,
      lineWidthMaxPixels: 12,
      getLineDashArray: (f: any) =>
        f.properties.live?.closed || f.properties.e.closed ? [6, 4] : [0, 0],
    }),
  );

  // gate access points: risk-coloured, queue-scaled rings
  layers.push(
    new ScatterplotLayer({
      id: 'world-gates',
      data: world.access_points.map((ap) => {
        const g = state?.gates[ap.gate_id];
        const color = g ? riskRgba(g.risk) : ap.kind === 'ENTRY' ? RGBA('#10b981') : RGBA('#f59e0b');
        const queue = g?.queue ?? 0;
        return {
          position: toLngLat(p, ap.position),
          color,
          radius: 34 + Math.min(120, queue / 4),
          _tipKey: `g:${ap.gate_id}`,
          tip: {
            title: ap.gate_id.replace(/_/g, ' '),
            rows: g
              ? [
                  { k: 'kind', v: `${ap.kind} · service ${ap.service_ppm}/min` },
                  { k: 'risk', v: g.risk, c: riskToHex(g.risk) },
                  { k: 'queue', v: `${Math.round(queue)} · wait ${g.queue_wait_min?.toFixed(1) ?? '—'} min` },
                  { k: 'arr/svc', v: `${g.arrivals_per_min.toFixed(1)}/${g.served_per_min.toFixed(1)} /min` },
                ]
              : [{ k: 'kind', v: `${ap.kind} · service ${ap.service_ppm}/min` }, { k: 'state', v: 'waiting for simulation' }],
          } as Tip,
        };
      }),
      pickable: true,
      stroked: true,
      filled: true,
      getPosition: (d) => d.position,
      getFillColor: (d) => d.color,
      getLineColor: (d) => d.color,
      getLineWidth: 2,
      getRadius: (d) => d.radius,
      radiusUnits: 'pixels',
      radiusMinPixels: 6,
    }),
  );

  // demand sources: mode glyphs + live rates
  layers.push(
    new IconLayer({
      id: 'world-sources',
      data: world.demand_sources.map((src) => {
        const st = state?.sources[src.id];
        const color = SOURCE_MODE_COLOR[src.kind] ?? RGBA('#7a5aa8');
        const icon = src.kind === 'METRO' ? 'metro' : src.kind === 'BUS' ? 'bus' : src.kind === 'PARKING' || src.kind === 'DROP_OFF' ? 'car' : 'walk';
        const rows: TipRow[] = [
          { k: 'type', v: `${src.kind} · ${src.data_source} data` },
          { k: 'share', v: `${Math.round(src.share * 100)}%` },
          { k: 'mode', v: st?.mode ?? 'walk' },
        ];
        if (st) {
          rows.push({ k: 'rate', v: `${st.current_rate_per_min.toFixed(1)}/min` });
          if (st.vehicles_per_min != null && st.vehicles_per_min > 0) {
            rows.push({ k: 'vehicles', v: `${st.vehicles_per_min.toFixed(2)}/min` });
          }
          rows.push({ k: 'total', v: String(st.emitted_total) });
        }
        return {
          position: toLngLat(p, src.position),
          icon,
          color,
          size: 26,
          _tipKey: `s:${src.id}`,
          tip: { title: src.name, rows } as Tip,
        };
      }),
      pickable: true,
      getPosition: (d) => d.position,
      getIcon: (d) => ICONS[d.icon],
      getSize: (d) => d.size,
      getColor: (d) => d.color,
      sizeUnits: 'pixels',
      sizeMinPixels: 8,
    }),
  );

  // prediction rings (edge or gate) — where congestion is heading
  layers.push(
    new ScatterplotLayer({
      id: 'world-preds',
      data: (state?.predictions ?? [])
        .map((pred) => {
          let pt: { x: number; y: number } | null = null;
          if (pred.kind === 'GATE') {
            const ap = world.access_points.find((a) => a.gate_id === pred.ref) ?? world.access_points.find((a) => a.id === pred.ref);
            pt = ap ? { x: ap.position.x, y: ap.position.y } : null;
          } else {
            const e = world.edges.find((ed) => ed.id === pred.ref);
            if (e && e.geometry.length) {
              const mid = e.geometry[Math.floor(e.geometry.length / 2)];
              pt = { x: mid.x, y: mid.y };
            }
          }
          if (!pt) return null;
          const color = riskRgba(pred.severity);
          return {
            position: toLngLat(p, pt),
            color,
            _tipKey: `pred:${pred.id}`,
            tip: {
              title: pred.ref.replace(/_/g, ' '),
              rows: [
                { k: 'severity', v: `${pred.severity} in ~${pred.in_minutes.toFixed(1)} min`, c: riskToHex(pred.severity) },
                { k: 'detail', v: pred.message },
              ],
            } as Tip,
          };
        })
        .filter(Boolean),
      pickable: true,
      stroked: true,
      filled: true,
      getPosition: (d) => d.position,
      getFillColor: (d) => [d.color[0], d.color[1], d.color[2], 30],
      getLineColor: (d) => d.color,
      getLineWidth: 2,
      getRadius: 110,
      radiusUnits: 'pixels',
      lineDashArray: [6, 4],
    }),
  );

  return layers;
}

// ── legacy env fallback (no world graph loaded yet) ────────────────────────
function envLayers(env: ExternalEnvironment, externalState: ExternalElementState[], p: GeoProjector): Layer[] {
  const layers: Layer[] = [];
  const features = env.roads
    .filter((r) => r.points.length >= 2)
    .map((r) => {
      const live = externalState.find((s) => s.id === r.id);
      const color = live && live.risk !== 'NORMAL' ? riskRgba(live.risk) : RGBA('#8a93a0', 200);
      return {
        type: 'Feature' as const,
        properties: { color },
        geometry: {
          type: 'LineString' as const,
          coordinates: r.points.map((pt) => toLngLat(p, pt)),
        },
      };
    });
  layers.push(
    new GeoJsonLayer({
      id: 'env-roads',
      data: { type: 'FeatureCollection', features } ,
      pickable: false,
      getLineColor: (f: any) => f.properties.color,
      getLineWidth: 3,
      lineWidthUnits: 'pixels',
    }),
  );

  const pts = [
    ...env.junctions.map((j) => ({ position: toLngLat(p, j.position), color: RGBA('#d7dbe0'), radius: 40, _tipKey: `j:${j.id}`, tip: { title: (j.name ?? j.id).replace(/_/g, ' '), rows: [{ k: 'kind', v: `${j.kind} junction` }] } as Tip })),
    ...env.transit.map((t) => ({ position: toLngLat(p, t.position), color: RGBA('#2f7ea0'), radius: 70, _tipKey: `t:${t.id}`, tip: { title: t.name, rows: [{ k: 'kind', v: `${t.kind} stop` }] } as Tip })),
    ...env.parking.map((pa) => ({ position: toLngLat(p, pa.position), color: RGBA('#10b981'), radius: 90, _tipKey: `p:${pa.id}`, tip: { title: pa.name, rows: [{ k: 'parking', v: `cap ${pa.capacity}` }] } as Tip })),
  ];
  layers.push(
    new ScatterplotLayer({
      id: 'env-points',
      data: pts,
      pickable: true,
      stroked: true,
      filled: true,
      getPosition: (d) => d.position,
      getFillColor: (d) => [d.color[0], d.color[1], d.color[2], 40],
      getLineColor: (d) => d.color,
      getLineWidth: 2,
      getRadius: (d) => d.radius,
      radiusUnits: 'pixels',
    }),
  );
  return layers;
}

// ── venue footprint + gates + bottlenecks on the map ───────────────────────
function venueLayers(venue: VenueModel, sim: SimulationState | null, p: GeoProjector): Layer[] {
  const layers: Layer[] = [];
  const footprint = venueGeoFootprint(p, venue);
  layers.push(
    new PolygonLayer({
      id: 'venue-footprint',
      data: [{ polygon: footprint, _tipKey: 'venue', action: 'venue', tip: { title: venue.name, rows: [{ k: 'size', v: `${venue.width}×${venue.height} m` }, { k: 'nodes', v: String(venue.nodes.length) }], note: 'Click to enter the venue twin' } as Tip }],
      pickable: true,
      getPolygon: (d) => d.polygon,
      filled: true,
      stroked: true,
      getFillColor: [58, 67, 80, 170],
      getLineColor: [245, 158, 11, 255],
      getLineWidth: 2,
      lineWidthUnits: 'pixels',
    }),
  );

  const gateNodes = venue.nodes.filter(
    (n) => n.type === 'ENTRY' || n.type === 'EXIT' || n.type === 'EMERGENCY_EXIT',
  );
  layers.push(
    new IconLayer({
      id: 'venue-gates',
      data: gateNodes.map((n) => {
        const live = sim?.nodes[n.id];
        const color = live ? riskRgba(live.risk) : n.type === 'ENTRY' ? RGBA('#10b981') : n.type === 'EMERGENCY_EXIT' ? RGBA('#ef4444') : RGBA('#f59e0b');
        const icon = n.type === 'ENTRY' ? 'gate' : n.type === 'EMERGENCY_EXIT' ? 'emergency' : 'exit';
        return {
          position: toLngLat(p, n.position),
          icon,
          color,
          size: 22,
          _tipKey: `vn:${n.id}`,
          tip: { title: n.id.replace(/_/g, ' '), rows: live ? [{ k: 'risk', v: `${live.risk} · ${Math.round(live.people)} people`, c: riskToHex(live.risk) }] : [{ k: 'kind', v: n.type }] } as Tip,
        };
      }),
      pickable: true,
      getPosition: (d) => d.position,
      getIcon: (d) => ICONS[d.icon],
      getSize: (d) => d.size,
      getColor: (d) => d.color,
      sizeUnits: 'pixels',
    }),
  );

  const bottlenecks = (sim?.bottlenecks ?? []).slice(0, 4);
  layers.push(
    new ScatterplotLayer({
      id: 'venue-bottlenecks',
      data: bottlenecks
        .map((b) => {
          const node = venue.nodes.find((n) => n.id === b.location || b.location.includes(n.id));
          const edge = venue.edges.find((e) => `${e.source}→${e.destination}` === b.location);
          const srcNode = edge ? venue.nodes.find((nn) => nn.id === edge.source) : null;
          const pt = node?.position ?? (edge ? { x: srcNode?.position.x ?? 500, y: srcNode?.position.y ?? 300 } : null);
          if (!pt) return null;
          const color = riskRgba(b.current_risk);
          return {
            position: toLngLat(p, pt),
            color,
            action: 'bottleneck',
            bottleneck: b,
            _tipKey: `bn:${b.location}`,
            tip: {
              title: b.location.replace(/→/g, ' → '),
              rows: [
                { k: 'risk', v: `${b.current_risk} · queue ${Math.round(b.queue)}`, c: riskToHex(b.current_risk) },
                { k: 'detail', v: b.explanation },
              ],
            } as Tip,
          };
        })
        .filter(Boolean),
      pickable: true,
      stroked: true,
      filled: true,
      getPosition: (d) => d.position,
      getFillColor: (d) => [d.color[0], d.color[1], d.color[2], 38],
      getLineColor: (d) => d.color,
      getLineWidth: 3,
      getRadius: 120,
      radiusUnits: 'pixels',
    }),
  );
  return layers;
}

// top-level static builder — memoized by the caller
export function buildStaticLayers(ctx: MapLayerContext): Layer[] {
  const { venue, env, world, sim, state, externalState, showLive, projector } = ctx;
  const p = projector;
  const layers: Layer[] = [];

  // the map is primary: venue footprint is always anchored, world first
  layers.push(...venueLayers(venue, sim, p));

  if (world) {
    layers.push(...worldLayers(world, showLive ? state : null, p));
  } else if (env) {
    layers.push(...envLayers(env, showLive ? externalState : [], p));
  }

  return layers;
}