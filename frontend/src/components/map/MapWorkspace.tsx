import { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, Polygon, Polyline, Circle, Marker, Popup, Tooltip, useMap } from 'react-leaflet';
import { Icon, latLngBounds, type LatLngExpression } from 'leaflet';
import { ArrowRight } from 'lucide-react';
import 'leaflet/dist/leaflet.css';
import type {
  Bottleneck,
  ExternalEnvironment,
  ExternalElementState,
  SimulationState,
  VenueModel,
  WorldGraph,
  WorldState,
} from '../../lib/types';
import {
  DEFAULT_ANCHOR,
  GeoProjector,
  venueGeoFootprint,
  envBoundsExtent,
  type GeoAnchor,
} from '../../lib/geoProjection';

const GATE_ICON = new Icon({
  iconUrl:
    'data:image/svg+xml;base64,' +
    btoa(
      '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0a0c0e" stroke-width="2"><path d="M20 5H4v14h16V5zM8 5v14M16 5v14" /></svg>',
    ),
  iconSize: [20, 20],
  iconAnchor: [10, 10],
});

const EXIT_ICON = new Icon({
  iconUrl:
    'data:image/svg+xml;base64,' +
    btoa(
      '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0a0c0e" stroke-width="2"><path d="M5 12h13M14 6l6 6-6 6"/></svg>',
    ),
  iconSize: [20, 20],
  iconAnchor: [10, 10],
});

const EMERGENCY_ICON = new Icon({
  iconUrl:
    'data:image/svg+xml;base64,' +
    btoa(
      '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0a0c0e" stroke-width="2"><path d="M12 2L2 22h20L12 2z"/></svg>',
    ),
  iconSize: [20, 20],
  iconAnchor: [10, 10],
});

const ROAD_COLOR: Record<string, string> = {
  ARTERIAL: '#8a93a0',
  MAJOR: '#b0b8c2',
  LOCAL: '#d7dbe0',
  ACCESS: '#f59e0b',
  RING: '#6b7480',
};

function riskColor(risk: string): string {
  if (risk === 'CRITICAL') return '#ef4444';
  if (risk === 'ELEVATED') return '#f59e0b';
  if (risk === 'HIGH') return '#ef4444';
  return '#10b981';
}

// --------------------------------------------------------------------------- //
//  Auto-fit the map to the environment extent (world bbox or env bbox)
// --------------------------------------------------------------------------- //
function FitBounds({
  projector,
  bbox,
}: {
  projector: GeoProjector;
  bbox: { min_x: number; min_y: number; max_x: number; max_y: number };
}) {
  const map = useMap();
  useEffect(() => {
    const pts = envBoundsExtent(projector, bbox);
    const bounds = latLngBounds(pts);
    map.fitBounds(bounds, { padding: [40, 40] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projector, bbox]);
  return null;
}

// --------------------------------------------------------------------------- //
//  Road polylines with live congestion coloring
// --------------------------------------------------------------------------- //
function RoadLayer({
  env,
  projector,
  externalState,
}: {
  env: ExternalEnvironment;
  projector: GeoProjector;
  externalState: ExternalElementState[];
}) {
  return (
    <>
      {env.roads.map((r) => {
        const latlngs = r.points.map((p) => projector.toLatLng(p.x, p.y));
        const live = externalState.find((s) => s.id === r.id);
        const color = live && live.risk !== 'NORMAL' ? riskColor(live.risk) : ROAD_COLOR[r.kind];
        const weight = live ? (live.congestion > 0.7 ? 6 : live.congestion > 0.4 ? 4.5 : 3) : 3;
        return (
          <Polyline
            key={r.id}
            positions={latlngs}
            pathOptions={{ color, weight, opacity: live ? 0.95 : 0.7 }}
          >
            {live && (
              <Tooltip sticky>
                <div className="mono-tabular text-[10px]">
                  <b>{r.name ?? r.id.replace(/_/g, ' ')}</b>
                  <div>risk {live.risk}</div>
                  <div>queue {live.queue_veh} veh</div>
                  <div>people {live.people_accumulated}</div>
                  {live.clearance_min != null && <div>clear ~{live.clearance_min.toFixed(1)} min</div>}
                </div>
              </Tooltip>
            )}
          </Polyline>
        );
      })}
      {env.junctions.map((j) => {
        const [lat, lng] = projector.toLatLng(j.position.x, j.position.y);
        const live = externalState.find((s) => s.id === j.id);
        return (
          <Circle key={j.id} center={[lat, lng]} radius={projector.metersToDegLat(40)} pathOptions={{ color: live ? riskColor(live.risk) : '#d7dbe0', weight: 2, fillOpacity: 0.6 }}>
            <Tooltip sticky>
              <div className="mono-tabular text-[10px]">
                <b>{j.name ?? j.id.replace(/_/g, ' ')}</b>
                <div>{j.kind} junction</div>
                {live && <div>risk {live.risk}</div>}
              </div>
            </Tooltip>
          </Circle>
        );
      })}
    </>
  );
}

// --------------------------------------------------------------------------- //
//  Crowd flow on the street network. The backend tracks real accumulated
//  person counts per road element (people leaving gates drain onto the nearest
//  road). We render that real data as animated flows streaming outward from the
//  venue along each road — sized and coloured by the actual congestion. This is
//  a truthful rendering of sim.external.elements, never a fabricated count.
// --------------------------------------------------------------------------- //
function CrowdFlowLayer({
  env,
  projector,
  externalState,
}: {
  env: ExternalEnvironment;
  projector: GeoProjector;
  externalState: ExternalElementState[];
}) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 250);
    return () => clearInterval(id);
  }, []);

  const flows = useMemo(() => {
    return env.roads
      .filter((r) => r.points.length >= 2)
      .map((r) => {
        const live = externalState.find((s) => s.id === r.id);
        const count = live ? Math.min(14, Math.max(1, Math.round(live.people_accumulated / 6))) : 0;
        return {
          id: r.id,
          points: r.points,
          count,
          color: live && live.risk !== 'NORMAL' ? riskColor(live.risk) : ROAD_COLOR[r.kind],
          people: live?.people_accumulated ?? 0,
        };
      })
      .filter((f) => f.count > 0);
  }, [env, externalState]);

  // deterministic per-road phase offsets so motion looks continuous
  const phase = (() => {
    const t = Date.now() / 1000;
    return flows.map((f) => {
      let h = 0;
      for (const c of f.id) h = (h * 31 + c.charCodeAt(0)) % 997;
      return (t * 0.12 + h / 997) % 1;
    });
  })();

  return (
    <>
      {flows.map((f, fi) => {
        const n = f.points.length;
        const step = 1 / Math.max(f.count, 1);
        const dots: { pos: LatLngExpression; color: string; r: number }[] = [];
        for (let i = 0; i < f.count; i++) {
          const u = (phase[fi] + i * step) % 1;
          const seg = Math.min(n - 2, Math.floor(u * (n - 1)));
          const t = u * (n - 1) - seg;
          const a = f.points[seg];
          const b = f.points[seg + 1];
          const lat = a.y + (b.y - a.y) * t;
          const lng = a.x + (b.x - a.x) * t;
          dots.push({ pos: projector.toLatLng(lat, lng), color: f.color, r: f.people > 0 ? 26 : 20 });
        }
        return dots.map((d, di) => (
          <Circle
            key={`${f.id}-${di}`}
            center={d.pos}
            radius={d.r}
            pathOptions={{ color: d.color, weight: 2, fillColor: d.color, fillOpacity: 0.85 }}
          />
        ));
      })}
    </>
  );
}

// --------------------------------------------------------------------------- //
//  Transit + parking markers
// --------------------------------------------------------------------------- //
function TransitLayer({ env, projector }: { env: ExternalEnvironment; projector: GeoProjector }) {
  const transitColor: Record<string, string> = { BUS: '#2f7ea0', TRAM: '#7a5aa8', RAIL: '#ef4444' };
  return (
    <>
      {env.transit.map((t) => {
        const [lat, lng] = projector.toLatLng(t.position.x, t.position.y);
        return (
          <Circle
            key={t.id}
            center={[lat, lng]}
            radius={projector.metersToDegLat(70)}
            pathOptions={{ color: transitColor[t.kind] ?? '#6b7480', fillOpacity: 0.35, weight: 2 }}
          >
            <Tooltip sticky>
              <div className="mono-tabular text-[10px]">
                <b>{t.name}</b>
                <div>{t.kind} stop</div>
              </div>
            </Tooltip>
          </Circle>
        );
      })}
      {env.parking.map((p) => {
        const [lat, lng] = projector.toLatLng(p.position.x, p.position.y);
        return (
          <Circle
            key={p.id}
            center={[lat, lng]}
            radius={projector.metersToDegLat(90)}
            pathOptions={{ color: '#10b981', fillOpacity: 0.25, weight: 2, dashArray: '4 4' }}
          >
            <Tooltip sticky>
              <div className="mono-tabular text-[10px]">
                <b>{p.name}</b>
                <div>parking · cap {p.capacity}</div>
              </div>
            </Tooltip>
          </Circle>
        );
      })}
    </>
  );
}

// --------------------------------------------------------------------------- //
//  World layer — the map is part of the simulation. The backend steps a unified
//  external graph (demand sources → roads → venue gates → outer sinks) inside
//  sim.world. We render that real state: edge flow/risk, animated movement,
//  gate queues, demand sources and predictions. Never a fabricated count.
// --------------------------------------------------------------------------- //
const WORLD_ROAD = '#8a93a0';
const WORLD_FOOTPATH = '#b0b8c2';
const REROUTE_COLOR = '#8d6be8';
const CLOSED_COLOR = '#4a4f57';

function WorldFlowLayer({
  world,
  state,
  projector,
}: {
  world: WorldGraph;
  state: WorldState | null;
  projector: GeoProjector;
}) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 250);
    return () => clearInterval(id);
  }, []);

  const flows = useMemo(() => {
    return world.edges
      .filter((e) => e.geometry.length >= 2)
      .map((e) => {
        const live = state?.edges[e.id];
        const rate = live?.flow_per_min ?? 0;
        const count = Math.min(12, Math.max(0, Math.round(rate / 24)));
        let color = live?.closed
          ? CLOSED_COLOR
          : live?.rerouted
            ? REROUTE_COLOR
            : live && live.risk !== 'NORMAL'
              ? riskColor(live.risk)
              : e.kind === 'FOOTPATH' || e.kind === 'GATE_LINK'
                ? WORLD_FOOTPATH
                : WORLD_ROAD;
        return { id: e.id, geometry: e.geometry, count, color, people: live?.people ?? 0 };
      })
      .filter((f) => f.count > 0);
  }, [world, state]);

  const phase = (() => {
    const t = Date.now() / 1000;
    return flows.map((f) => {
      let h = 0;
      for (const c of f.id) h = (h * 31 + c.charCodeAt(0)) % 997;
      return (t * 0.12 + h / 997) % 1;
    });
  })();

  return (
    <>
      {flows.map((f, fi) => {
        const n = f.geometry.length;
        const step = 1 / Math.max(f.count, 1);
        const dots: { pos: LatLngExpression; color: string; r: number }[] = [];
        for (let i = 0; i < f.count; i++) {
          const u = (phase[fi] + i * step) % 1;
          const seg = Math.min(n - 2, Math.floor(u * (n - 1)));
          const t = u * (n - 1) - seg;
          const a = f.geometry[seg];
          const b = f.geometry[seg + 1];
          const lat = a.y + (b.y - a.y) * t;
          const lng = a.x + (b.x - a.x) * t;
          dots.push({ pos: projector.toLatLng(lat, lng), color: f.color, r: f.people > 0 ? 26 : 20 });
        }
        return dots.map((d, di) => (
          <Circle
            key={`${f.id}-${di}`}
            center={d.pos}
            radius={d.r}
            pathOptions={{ color: d.color, weight: 2, fillColor: d.color, fillOpacity: 0.85 }}
          />
        ));
      })}
    </>
  );
}

function WorldLayer({
  world,
  state,
  projector,
  live,
}: {
  world: WorldGraph;
  state: WorldState | null;
  projector: GeoProjector;
  live: boolean;
}) {
  const gateState = (gateId: string) => state?.gates[gateId];
  const gateAt = (ref: string) =>
    world.access_points.find((ap) => ap.gate_id === ref) ??
    world.access_points.find((ap) => ap.id === ref);

  return (
    <>
      {/* edges — base stroke coloured by live risk / closed / rerouted */}
      {world.edges.map((e) => {
        if (e.geometry.length < 2) return null;
        const latlngs = e.geometry.map((p) => projector.toLatLng(p.x, p.y));
        const liveE = state?.edges[e.id];
        let color = liveE?.closed
          ? CLOSED_COLOR
          : liveE?.rerouted
            ? REROUTE_COLOR
            : liveE && liveE.risk !== 'NORMAL'
              ? riskColor(liveE.risk)
              : e.kind === 'FOOTPATH' || e.kind === 'GATE_LINK'
                ? WORLD_FOOTPATH
                : WORLD_ROAD;
        const weight = liveE ? Math.min(8, 2 + Math.round((liveE.flow_per_min ?? 0) / 60)) : 2.5;
        return (
          <Polyline
            key={e.id}
            positions={latlngs}
            pathOptions={{
              color,
              weight,
              opacity: liveE ? 0.95 : 0.55,
              dashArray: e.closed || liveE?.closed ? '6 4' : undefined,
            }}
          >
            <Tooltip sticky>
              <div className="mono-tabular text-[10px]">
                <b>{e.id.replace(/_/g, ' ')}</b>
                <div>{e.kind} · {Math.round(e.length_m)} m</div>
                {liveE ? (
                  <>
                    <div style={{ color }}>risk {liveE.risk}</div>
                    <div>flow {liveE.flow_per_min.toFixed(1)}/min</div>
                    <div>people {liveE.people}</div>
                    {liveE.time_to_critical_min != null && (
                      <div>~{liveE.time_to_critical_min.toFixed(1)} min to critical</div>
                    )}
                    {liveE.closed && <div className="text-od-danger">CLOSED</div>}
                    {liveE.rerouted && <div className="text-od-warn">REROUTED</div>}
                  </>
                ) : (
                  <div>cap {Math.round(e.capacity_estimate)}/h · est</div>
                )}
              </div>
            </Tooltip>
          </Polyline>
        );
      })}

      {/* animated flow dots — real sim.world edge flows */}
      {live && <WorldFlowLayer world={world} state={state} projector={projector} />}

      {/* access points — gate connectors with live queue badges */}
      {world.access_points.map((ap) => {
        const [lat, lng] = projector.toLatLng(ap.position.x, ap.position.y);
        const g = gateState(ap.gate_id);
        const color = g ? riskColor(g.risk) : ap.kind === 'ENTRY' ? '#10b981' : '#f59e0b';
        const queue = g?.queue ?? 0;
        return (
          <Circle
            key={ap.id}
            center={[lat, lng]}
            radius={projector.metersToDegLat(34)}
            pathOptions={{ color, weight: 2, fillColor: color, fillOpacity: 0.75 }}
          >
            <Tooltip direction="top" offset={[0, -6]}>
              <div className="mono-tabular text-[10px]">
                <b>{ap.gate_id.replace(/_/g, ' ')}</b>
                <div>{ap.kind} · service {ap.service_ppm}/min</div>
                {g ? (
                  <>
                    <div style={{ color }}>risk {g.risk}</div>
                    <div>queue {Math.round(queue)} · wait {g.queue_wait_min?.toFixed(1) ?? '—'} min</div>
                    <div>arr {g.arrivals_per_min.toFixed(1)}/min · svc {g.served_per_min.toFixed(1)}/min</div>
                  </>
                ) : (
                  <div>waiting for simulation</div>
                )}
              </div>
            </Tooltip>
          </Circle>
        );
      })}

      {/* demand sources — where the external crowd comes from */}
      {world.demand_sources.map((src) => {
        const [lat, lng] = projector.toLatLng(src.position.x, src.position.y);
        const st = state?.sources[src.id];
        return (
          <Circle
            key={src.id}
            center={[lat, lng]}
            radius={projector.metersToDegLat(60)}
            pathOptions={{ color: '#7a5aa8', fillOpacity: 0.25, weight: 2, dashArray: '4 4' }}
          >
            <Tooltip sticky>
              <div className="mono-tabular text-[10px]">
                <b>{src.name}</b>
                <div>{src.kind} · {src.data_source} data</div>
                <div>share {Math.round(src.share * 100)}%</div>
                {st && <div>rate {st.current_rate_per_min.toFixed(1)}/min · total {Math.round(st.emitted_total)}</div>}
              </div>
            </Tooltip>
          </Circle>
        );
      })}

      {/* prediction rings — where congestion is heading (edge or gate) */}
      {(state?.predictions ?? []).map((p) => {
        let pt: { x: number; y: number } | null = null;
        if (p.kind === 'GATE') {
          const ap = gateAt(p.ref);
          pt = ap ? { x: ap.position.x, y: ap.position.y } : null;
        } else {
          const e = world.edges.find((ed) => ed.id === p.ref);
          if (e && e.geometry.length) {
            const mid = e.geometry[Math.floor(e.geometry.length / 2)];
            pt = { x: mid.x, y: mid.y };
          }
        }
        if (!pt) return null;
        const [lat, lng] = projector.toLatLng(pt.x, pt.y);
        const color = riskColor(p.severity);
        return (
          <Circle
            key={`pred-${p.id}`}
            center={[lat, lng]}
            radius={projector.metersToDegLat(110)}
            pathOptions={{ color, weight: 2, dashArray: '6 4', fillColor: color, fillOpacity: 0.12 }}
          >
            <Tooltip sticky>
              <div className="mono-tabular text-[10px]">
                <b>{p.ref.replace(/_/g, ' ')}</b>
                <div style={{ color }}>{p.severity} in ~{p.in_minutes.toFixed(1)} min</div>
                <div>{p.message}</div>
              </div>
            </Tooltip>
          </Circle>
        );
      })}
    </>
  );
}

// --------------------------------------------------------------------------- //
//  Stadium footprint + gates + exits + bottleneck rings (clickable)
// --------------------------------------------------------------------------- //
function VenueLayer({
  venue,
  projector,
  sim,
  onOpenVenue,
  onSelectBottleneck,
}: {
  venue: VenueModel;
  projector: GeoProjector;
  sim: SimulationState | null;
  onOpenVenue: () => void;
  onSelectBottleneck: (b: Bottleneck) => void;
}) {
  const footprint = useMemo(() => venueGeoFootprint(projector, venue), [projector, venue]);
  return (
    <>
      <Polygon
        positions={footprint}
        pathOptions={{ color: '#f59e0b', weight: 2, fillColor: '#3a4350', fillOpacity: 0.55 }}
        eventHandlers={{ click: onOpenVenue }}
      >
        <Popup>
          <div className="mono-tabular text-[11px]">
            <b>{venue.name}</b>
            <div>{venue.width}×{venue.height} m venue</div>
            <button className="btn btn-solid mt-1.5 w-full" onClick={onOpenVenue}>ENTER VENUE</button>
          </div>
        </Popup>
      </Polygon>
      {venue.nodes
        .filter((n) => n.type === 'ENTRY' || n.type === 'EXIT' || n.type === 'EMERGENCY_EXIT')
        .map((n) => {
          const [lat, lng] = projector.toLatLng(n.position.x, n.position.y);
          const live = sim?.nodes[n.id];
          const icon = n.type === 'ENTRY' ? GATE_ICON : n.type === 'EMERGENCY_EXIT' ? EMERGENCY_ICON : EXIT_ICON;
          const color = live ? riskColor(live.risk) : n.type === 'ENTRY' ? '#10b981' : n.type === 'EMERGENCY_EXIT' ? '#ef4444' : '#f59e0b';
          return (
            <Marker key={n.id} position={[lat, lng]} icon={icon}>
              <Tooltip direction="top" offset={[0, -8]}>
                <div className="mono-tabular text-[10px]">
                  <b>{n.id.replace(/_/g, ' ')}</b>
                  <div style={{ color }}>
                    {live ? `${live.risk} · ${Math.round(live.people)} people` : n.type}
                  </div>
                </div>
              </Tooltip>
            </Marker>
          );
        })}
      {/* predicted bottleneck rings over the venue — click to investigate */}
      {(sim?.bottlenecks ?? []).slice(0, 4).map((b) => {
        const node = venue.nodes.find((n) => n.id === b.location || b.location.includes(n.id));
        const edge = venue.edges.find((e) => `${e.source}→${e.destination}` === b.location);
        const srcNode = edge ? venue.nodes.find((nn) => nn.id === edge.source) : null;
        const pt =
          node?.position ??
          (edge
            ? { x: srcNode?.position.x ?? 500, y: srcNode?.position.y ?? 300 }
            : null);
        if (!pt) return null;
        const [lat, lng] = projector.toLatLng(pt.x, pt.y);
        const color = riskColor(b.current_risk);
        return (
          <Circle
            key={`bn-${b.location}`}
            center={[lat, lng]}
            radius={projector.metersToDegLat(120)}
            pathOptions={{ color, weight: 3, fillOpacity: 0.15 }}
            eventHandlers={{ click: () => onSelectBottleneck(b) }}
          >
            <Tooltip sticky>
              <div className="mono-tabular text-[10px]">
                <b>{b.location.replace(/→/g, ' → ')}</b>
                <div style={{ color }}>{b.current_risk} · queue {Math.round(b.queue)}</div>
                <div>{b.explanation}</div>
              </div>
            </Tooltip>
          </Circle>
        );
      })}
    </>
  );
}

// --------------------------------------------------------------------------- //
//  Main map workspace — the home screen
// --------------------------------------------------------------------------- //
export default function MapWorkspace({
  venue,
  env,
  world,
  sim,
  cfSim,
  worldState,
  cfWorldState,
  compareSide,
  anchor,
  onAnchorChange,
  onOpenVenue,
  onSelectBottleneck,
}: {
  venue: VenueModel;
  env: ExternalEnvironment | null;
  world: WorldGraph | null;
  sim: SimulationState | null;
  cfSim: SimulationState | null;
  worldState: WorldState | null;
  cfWorldState: WorldState | null;
  compareSide: 'baseline' | 'whatif';
  anchor: GeoAnchor;
  onAnchorChange: (a: GeoAnchor) => void;
  onOpenVenue: () => void;
  onSelectBottleneck: (b: Bottleneck) => void;
}) {
  const projector = useMemo(() => new GeoProjector(anchor, venue), [anchor, venue]);
  const shownSim: SimulationState | null = cfSim && compareSide === 'whatif' ? cfSim : sim;
  const shownWorld: WorldState | null =
    cfWorldState && compareSide === 'whatif' ? cfWorldState : worldState;
  const externalState: ExternalElementState[] = useMemo(
    () => Object.values(shownSim?.external?.elements ?? {}),
    [shownSim],
  );
  const [showLive, setShowLive] = useState(true);
  const [anchorDirty, setAnchorDirty] = useState(false);
  const [editAnchor, setEditAnchor] = useState<GeoAnchor>(anchor);
  const [anchorError, setAnchorError] = useState<string | null>(null);

  // keep the local editor in sync when the anchor is lifted upstream
  useEffect(() => {
    setEditAnchor(anchor);
  }, [anchor]);

  const totalPeople = useMemo(() => {
    if (world && shownWorld) {
      return Object.values(shownWorld.edges).reduce((acc, e) => acc + e.people, 0);
    }
    return externalState.reduce((acc, el) => acc + el.people_accumulated, 0);
  }, [world, shownWorld, externalState]);
  const congested = world && shownWorld
    ? shownWorld.congested_edges
    : externalState.filter((el) => el.risk !== 'NORMAL').length;

  const mapBbox = world?.bbox ??
    (env?.bbox as { min_x: number; min_y: number; max_x: number; max_y: number } | undefined) ?? {
      min_x: 0,
      min_y: 0,
      max_x: venue.width,
      max_y: venue.height,
    };

  const applyAnchor = () => {
    const lat = Number(editAnchor.lat);
    const lng = Number(editAnchor.lng);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      setAnchorError('Invalid coordinates — lat must be -90..90, lng -180..180');
      return;
    }
    setAnchorError(null);
    onAnchorChange({ lat, lng, name: editAnchor.name || 'Custom anchor' });
    setAnchorDirty(false);
  };

  return (
    <div className="relative h-full w-full">
      <MapContainer
        center={projector.venueCenter()}
        zoom={15}
        style={{ height: '100%', width: '100%' }}
        className="z-0"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds projector={projector} bbox={mapBbox} />
        <VenueLayer venue={venue} projector={projector} sim={shownSim} onOpenVenue={onOpenVenue} onSelectBottleneck={onSelectBottleneck} />
        {world ? (
          <WorldLayer world={world} state={showLive ? shownWorld : null} projector={projector} live={showLive} />
        ) : env ? (
          <>
            <RoadLayer env={env} projector={projector} externalState={showLive ? externalState : []} />
            {showLive && <CrowdFlowLayer env={env} projector={projector} externalState={externalState} />}
            <TransitLayer env={env} projector={projector} />
          </>
        ) : null}
      </MapContainer>

      {/* overlay controls */}
      <div className="absolute left-3 top-3 z-[1000] flex flex-col gap-1.5 border border-od-line bg-od-panel/95 p-2 shadow-lg backdrop-blur">
        <div className="flex items-center justify-between gap-4">
          <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-od-ink">
            {world ? `World map · ${world.provider}` : `Live map · ${env?.source ?? '—'}`}
          </span>
          <button
            onClick={() => setShowLive((v) => !v)}
            className={`btn ${showLive ? 'btn-solid' : 'btn-ghost'} !py-0.5`}
          >
            {showLive ? 'LIVE' : 'BASE'}
          </button>
        </div>
        {world && world.provenance.notes.length > 0 && (
          <div className="max-w-[240px] text-[9px] leading-snug text-od-muted">
            {world.provenance.notes[0]}
          </div>
        )}
        <div className="flex flex-wrap gap-3 text-[9px] uppercase tracking-[0.12em] text-od-muted">
          <span className="inline-flex items-center gap-1"><span className="h-2 w-4 inline-block" style={{ background: '#10b981' }} />gate</span>
          <span className="inline-flex items-center gap-1"><span className="h-2 w-4 inline-block" style={{ background: '#f59e0b' }} />exit</span>
          <span className="inline-flex items-center gap-1"><span className="h-2 w-4 inline-block" style={{ background: '#ef4444' }} />emergency</span>
          {world && (
            <>
              <span className="inline-flex items-center gap-1"><span className="h-2 w-4 inline-block" style={{ background: '#8d6be8' }} />rerouted</span>
              <span className="inline-flex items-center gap-1"><span className="h-2 w-4 inline-block" style={{ background: '#7a5aa8' }} />source</span>
            </>
          )}
          <span className="inline-flex items-center gap-1"><span className="h-2 w-4 inline-block" style={{ background: '#ef4444' }} />critical</span>
          <span className="inline-flex items-center gap-1"><span className="h-2 w-4 inline-block" style={{ background: '#f59e0b' }} />elevated</span>
        </div>
        {showLive && (
          <div className="flex items-center gap-3 border-t border-od-line pt-1.5 text-[9px] uppercase tracking-[0.12em] text-od-muted">
            <span>{world ? 'roads' : 'streets'} <b className="num text-od-ink">{totalPeople.toLocaleString()}</b> people</span>
            <span>risk <b className="num text-od-danger">{congested}</b> elements</span>
          </div>
        )}
      </div>

      {/* venue drill-down card */}
      <button
        className="absolute left-3 top-1/2 z-[1000] -translate-y-1/2 max-w-[210px] border border-od-line bg-od-panel/95 p-2 text-left shadow-lg backdrop-blur transition-transform hover:-translate-y-[calc(50%+2px)]"
        onClick={onOpenVenue}
        title="Open the inside-venue 3D digital twin"
      >
        <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-od-ink">{venue.name}</span>
        <span className="mt-1 block text-[9px] leading-snug text-od-muted">
          {venue.width}×{venue.height} m · {venue.nodes.length} nodes · click to enter
        </span>
        <span className="mt-1.5 inline-flex items-center gap-1 text-[9px] font-bold uppercase tracking-[0.14em] text-od-warn">
          ENTER VENUE <ArrowRight className="h-3 w-3" />
        </span>
      </button>

      {/* anchor / reprojection panel */}
      <div className="absolute bottom-3 right-3 z-[1000] w-72 border border-od-line bg-od-panel/95 p-3 shadow-lg backdrop-blur">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-od-ink">Geo anchor</span>
          <span className="chip"><span className={`status-dot ${env?.source === 'LIVE_OSM' ? 'is-ok' : 'is-warn'}`} />{env?.source ?? 'WORLD'}</span>
        </div>
        <div className="mt-2 space-y-1.5">
          <label className="block space-y-0.5">
            <span className="text-[8px] uppercase tracking-[0.1em] text-od-muted">Latitude</span>
            <input
              type="number"
              step="0.0001"
              value={editAnchor.lat}
              onChange={(e) => { setEditAnchor({ ...editAnchor, lat: Number(e.target.value) }); setAnchorDirty(true); }}
              className="field w-full text-[11px] mono-tabular"
            />
          </label>
          <label className="block space-y-0.5">
            <span className="text-[8px] uppercase tracking-[0.1em] text-od-muted">Longitude</span>
            <input
              type="number"
              step="0.0001"
              value={editAnchor.lng}
              onChange={(e) => { setEditAnchor({ ...editAnchor, lng: Number(e.target.value) }); setAnchorDirty(true); }}
              className="field w-full text-[11px] mono-tabular"
            />
          </label>
          <label className="block space-y-0.5">
            <span className="text-[8px] uppercase tracking-[0.1em] text-od-muted">Label</span>
            <input
              value={editAnchor.name}
              onChange={(e) => { setEditAnchor({ ...editAnchor, name: e.target.value }); setAnchorDirty(true); }}
              className="field w-full text-[11px]"
            />
          </label>
        </div>
        {anchorError && <div className="mt-1.5 text-[9px] text-od-danger">{anchorError}</div>}
        <button className="btn btn-solid mt-2 w-full" onClick={applyAnchor} disabled={!anchorDirty}>
          Re-anchor venue on map
        </button>
        <button className="btn btn-ghost mt-1 w-full" onClick={() => { onAnchorChange(DEFAULT_ANCHOR); setEditAnchor(DEFAULT_ANCHOR); setAnchorDirty(true); setAnchorError(null); }}>
          Reset to {DEFAULT_ANCHOR.name}
        </button>
      </div>
    </div>
  );
}