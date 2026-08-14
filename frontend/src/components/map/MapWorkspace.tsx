import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { MapboxOverlay } from '@deck.gl/mapbox';
import type { PickingInfo } from '@deck.gl/core';
import { ArrowRight } from 'lucide-react';
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
  type GeoAnchor,
} from '../../lib/geoProjection';
import {
  buildStaticLayers,
  buildTripLayers,
  buildTripRows,
  type Tip,
} from './mapLayers';

// --------------------------------------------------------------------------- //
//  Map-centric workspace — the map is the interface.
//
//  MapLibre GL JS renders the real basemap; deck.gl (MapboxOverlay, interleaved)
//  renders the world graph, live congestion, gate queues, demand sources and
//  animated per-mode transport — all derived from backend state. The 3D venue
//  twin and the analysis rails remain the surrounding UI.
// --------------------------------------------------------------------------- //

const OSM_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '&copy; OpenStreetMap contributors',
      maxzoom: 19,
    },
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
};

interface TipState {
  x: number;
  y: number;
  tip: Tip;
}

function TipCard({ tip }: { tip: Tip }) {
  return (
    <div className="mono-tabular max-w-[260px] border border-od-line bg-od-panel/95 p-2 text-[10px] leading-snug shadow-lg backdrop-blur">
      <div className="font-bold uppercase tracking-[0.12em] text-od-ink">{tip.title}</div>
      {tip.rows.map((r, i) => (
        <div key={i} className="mt-0.5 flex items-baseline justify-between gap-3 text-od-muted">
          <span>{r.k}</span>
          <span className="num text-od-ink" style={r.c ? { color: r.c } : undefined}>
            {r.v}
          </span>
        </div>
      ))}
      {tip.note && <div className="mt-1 text-od-muted">{tip.note}</div>}
    </div>
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
  const [tip, setTip] = useState<TipState | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const tipKeyRef = useRef<string | null>(null);

  // keep the editor in sync when the anchor is lifted upstream
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

  // ── map + deck overlay lifecycle ────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;
    const [lat, lng] = projector.venueCenter();
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OSM_STYLE,
      center: [lng, lat],
      zoom: 15,
    });
    mapRef.current = map;

    const overlay = new MapboxOverlay({ interleaved: true, layers: [] });
    map.addControl(overlay);
    overlayRef.current = overlay;
    setMapReady(true);

    return () => {
      overlayRef.current = null;
      map.removeControl(overlay);
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── fit the map to the world / env extent (anchor changes re-fit) ────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const bbox = world?.bbox ?? (env?.bbox as { min_x: number; min_y: number; max_x: number; max_y: number } | undefined) ?? {
      min_x: 0,
      min_y: 0,
      max_x: venue.width,
      max_y: venue.height,
    };
    const sw = projector.toLatLng(bbox.min_x, bbox.max_y); // [lat, lng]
    const ne = projector.toLatLng(bbox.max_x, bbox.min_y);
    map.fitBounds(
      [
        [sw[1], sw[0]],
        [ne[1], ne[0]],
      ],
      { padding: { top: 60, right: 280, bottom: 70, left: 80 }, maxZoom: 16.5 },
    );
  }, [mapReady, projector, world?.bbox, env?.bbox, venue]);

  const tipRef = useRef({ x: 0, y: 0 });
  const onHover = useCallback((info: PickingInfo) => {
    const o = info.object as { tip?: Tip; _tipKey?: string; properties?: { tip?: Tip; tipKey?: string } } | null;
    const t = o?.tip ?? o?.properties?.tip;
    if (!t) {
      setTip(null);
      tipKeyRef.current = null;
      return;
    }
    const key = o?._tipKey ?? o?.properties?.tipKey ?? String(info.index);
    if (tipKeyRef.current !== key) {
      tipKeyRef.current = key;
      setTip({ x: info.x, y: info.y, tip: t });
    } else if (info.x !== tipRef.current.x || info.y !== tipRef.current.y) {
      tipRef.current.x = info.x;
      tipRef.current.y = info.y;
      setTip((cur) => (cur ? { ...cur, x: info.x, y: info.y } : cur));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onClick = useCallback((info: PickingInfo) => {
    const obj = info.object as { action?: string; bottleneck?: Bottleneck } | null;
    if (!obj) return;
    if (obj.action === 'venue') onOpenVenue();
    else if (obj.action === 'bottleneck' && obj.bottleneck) onSelectBottleneck(obj.bottleneck);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── rAF animator: static layers memoized, trip layers rebuilt each frame ──
  const staticLayers = useMemo(
    () =>
      buildStaticLayers({
        venue,
        env,
        world,
        sim,
        state: shownWorld,
        externalState,
        showLive,
        projector,
      }),
    [venue, env, world, sim, shownWorld, externalState, showLive, projector],
  );
  const tripRows = useMemo(
    () => (world ? buildTripRows(world, shownWorld, projector) : { walk: [], car: [], bus: [], metro: [] }),
    [world, shownWorld, projector],
  );

  const layersRef = useRef({ staticLayers, tripRows });
  useEffect(() => {
    layersRef.current = { staticLayers, tripRows };
  }, [staticLayers, tripRows]);

  useEffect(() => {
    let raf = 0;
    let alive = true;
    const tick = () => {
      if (!alive) return;
      const overlay = overlayRef.current;
      if (overlay) {
        const time = (performance.now() / 1000) % 60;
        const { staticLayers: staticNow, tripRows: rowsNow } = layersRef.current;
        overlay.setProps({
          layers: [...staticNow, ...buildTripLayers(rowsNow, time)],
          onHover,
          onClick,
          getCursor: ({ isDragging, isHovering }) =>
            isDragging ? 'grabbing' : isHovering ? 'pointer' : 'default',
        });
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
    };
  }, [onHover, onClick]);

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
      <div ref={containerRef} className="h-full w-full" />

      {/* hover tooltip */}
      {tip && (
        <div
          className="pointer-events-none absolute z-[1000]"
          style={{ left: Math.min(tip.x + 14, window.innerWidth - 300), top: Math.min(tip.y + 14, window.innerHeight - 220) }}
        >
          <TipCard tip={tip.tip} />
        </div>
      )}

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
              <span className="inline-flex items-center gap-1"><span className="h-2 w-4 inline-block" style={{ background: '#a855f7' }} />metro</span>
              <span className="inline-flex items-center gap-1"><span className="h-2 w-4 inline-block" style={{ background: '#3b82f6' }} />bus</span>
              <span className="inline-flex items-center gap-1"><span className="h-2 w-4 inline-block" style={{ background: '#fb923c' }} />car</span>
              <span className="inline-flex items-center gap-1"><span className="h-2 w-4 inline-block" style={{ background: '#2dd4bf' }} />walk</span>
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