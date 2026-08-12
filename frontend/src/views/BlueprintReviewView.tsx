import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  Check,
  FileUp,
  Layers,
  Loader2,
  MousePointer2,
  Plus,
  RotateCcw,
  Trash2,
  Wand2,
  X,
} from 'lucide-react';
import { useSimulation } from '../store/SimulationContext';
import { api } from '../lib/api';
import type {
  BlueprintDetectionResult,
  BlueprintResult,
  Detection,
  ReconstructionReport,
} from '../lib/types';

type Stage = 'idle' | 'detecting' | 'review' | 'reconstructing' | 'done';

interface BlueprintReviewProps {
  initialFile: File | null;
  onOpenTwin: (result: BlueprintResult) => void;
  onExit: () => void;
}

const STEPS = ['Upload', 'Detect', 'Review', 'Reconstruct', 'Twin'];

// --------------------------------------------------------------------------- //
//  overlay palette (independent of the CSS theme so it stays readable on the
//  scanned blueprint itself)
// --------------------------------------------------------------------------- //
const GATE_COLOR: Record<string, string> = {
  ENTRY: '#2f9e63',
  EXIT: '#d8912f',
  EMERGENCY_EXIT: '#e0453c',
};

const REGION_COLOR: Record<string, string> = {
  FIELD: '#2f7d43',
  SEATING: '#8b95a1',
  CONCOURSE: '#5c8fb0',
  ROOM: '#8d6bb3',
  ZONE: '#7b5bd6',
  STAIR: '#8b95a1',
};

const WALL_COLOR = '#c9a24b';
const TEXT_COLOR = '#4fc3f7';

function centroidOf(d: Detection): { x: number; y: number } {
  const g = d.geometry;
  if (g.point) return { x: g.point.x, y: g.point.y };
  if (g.polygon && g.polygon.length) {
    const xs = g.polygon.map((p) => p.x);
    const ys = g.polygon.map((p) => p.y);
    return { x: xs.reduce((a, b) => a + b, 0) / xs.length, y: ys.reduce((a, b) => a + b, 0) / ys.length };
  }
  if (g.polyline && g.polyline.length) {
    const xs = g.polyline.map((p) => p.x);
    const ys = g.polyline.map((p) => p.y);
    return { x: xs.reduce((a, b) => a + b, 0) / xs.length, y: ys.reduce((a, b) => a + b, 0) / ys.length };
  }
  const b = g.bbox ?? [0, 0, 0, 0];
  return { x: (b[0] + b[2]) / 2, y: (b[1] + b[3]) / 2 };
}

function gateKindOf(d: Detection): string | null {
  const k = String(d.metadata?.kind ?? '').toUpperCase();
  return k in GATE_COLOR ? k : null;
}

function regionKindOf(d: Detection): string | null {
  const k = String(d.metadata?.kind ?? '').toUpperCase();
  return k in REGION_COLOR ? k : null;
}

function confColor(conf: number): string {
  if (conf >= 0.7) return '#3cb879';
  if (conf >= 0.5) return '#e2a64f';
  return '#ff5c55';
}

function pct(conf: number): string {
  return `${Math.round(Math.min(1, Math.max(0, conf)) * 100)}%`;
}

export default function BlueprintReviewView({ initialFile, onOpenTwin, onExit }: BlueprintReviewProps) {
  const { refreshCatalog, selectVenue } = useSimulation();
  const [stage, setStage] = useState<Stage>(initialFile ? 'detecting' : 'idle');
  const [file, setFile] = useState<File | null>(initialFile);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [detection, setDetection] = useState<BlueprintDetectionResult | null>(null);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [result, setResult] = useState<BlueprintResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [placeMode, setPlaceMode] = useState(false);

  const [showGates, setShowGates] = useState(true);
  const [showRegions, setShowRegions] = useState(true);
  const [showWalls, setShowWalls] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [showPaths, setShowPaths] = useState(true);
  const [showLowConf, setShowLowConf] = useState(true);

  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const svgRef = useRef<SVGSVGElement | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const dragRef = useRef<{
    id: string;
    kind: 'point' | 'region' | 'pan';
    startX: number;
    startY: number;
    base: { x: number; y: number } | null;
    bbox: [number, number, number, number] | null;
  } | null>(null);
  const mountedRef = useRef(true);

  const W = detection?.image.width_px ?? 1;
  const H = detection?.image.height_px ?? 1;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // revoke object URLs when the file changes / unmounts
  useEffect(() => {
    if (!file) {
      setImageUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setImageUrl(url);
    setStage('detecting');
    setError(null);
    api
      .detectBlueprint(file)
      .then((d) => {
        if (!mountedRef.current) return;
        setDetection(d);
        setDetections(d.detections);
        setSelectedId(null);
        setStage('review');
      })
      .catch((e) => {
        if (!mountedRef.current) return;
        setError(e instanceof Error ? e.message : 'Detection failed');
        setStage('idle');
      });
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const updateDetection = useCallback((id: string, fn: (d: Detection) => void) => {
    setDetections((prev) =>
      prev.map((d) => {
        if (d.id !== id) return d;
        const copy: Detection = { ...d, geometry: { ...d.geometry }, metadata: { ...d.metadata } };
        if (copy.geometry.point) copy.geometry.point = { ...copy.geometry.point };
        if (copy.geometry.bbox) copy.geometry.bbox = [...copy.geometry.bbox];
        if (copy.geometry.polygon) copy.geometry.polygon = copy.geometry.polygon.map((p) => ({ ...p }));
        fn(copy);
        return copy;
      }),
    );
  }, []);

  const deleteDetection = useCallback((id: string) => {
    setDetections((prev) => prev.filter((d) => d.id !== id));
    setSelectedId((cur) => (cur === id ? null : cur));
  }, []);

  const addGate = useCallback(() => {
    const id = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? `GATE_${crypto.randomUUID().slice(0, 6)}` : `GATE_${Date.now()}`;
    const x = W / 2;
    const y = H / 2;
    const newDet: Detection = {
      id,
      kind: 'GATE',
      geometry: {
        type: 'POINT',
        point: { x, y },
        bbox: [x - 9, y - 9, x + 9, y + 9],
      },
      confidence: 0.5,
      source: 'USER',
      metadata: { side: 'N', width_px: 18, kind: 'ENTRY' },
    };
    setDetections((prev) => [...prev, newDet]);
    setSelectedId(id);
    setPlaceMode(false);
  }, [W, H]);

  const pickFile = useCallback((f: File | null) => {
    if (!f) return;
    setFile(f);
    setResult(null);
  }, []);

  // ------------------------------------------------------------------ //
  //  canvas math: client <-> svg space (respects the current pan/zoom view)
  // ------------------------------------------------------------------ //
  const toSvgPoint = useCallback((clientX: number, clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return null;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const p = new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
  }, []);

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      if (stage !== 'review') return;
      const pt = toSvgPoint(e.clientX, e.clientY);
      if (!pt) return;
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.22 : 1 / 1.22;
      setView((v) => {
        const k = Math.min(14, Math.max(0.4, v.k * factor));
        const nx = pt.x - ((pt.x - v.x) * v.k) / k;
        const ny = pt.y - ((pt.y - v.y) * v.k) / k;
        return { x: nx, y: ny, k };
      });
    },
    [stage, toSvgPoint],
  );

  const startDrag = useCallback(
    (e: React.PointerEvent, det: Detection) => {
      if (stage !== 'review') return;
      e.stopPropagation();
      const pt = toSvgPoint(e.clientX, e.clientY);
      if (!pt) return;
      (e.target as Element).setPointerCapture?.(e.pointerId);
      setSelectedId(det.id);
      const g = det.geometry;
      if (g.point) {
        dragRef.current = {
          id: det.id,
          kind: 'point',
          startX: pt.x,
          startY: pt.y,
          base: { x: g.point.x, y: g.point.y },
          bbox: (g.bbox ? [...g.bbox] : null) as [number, number, number, number] | null,
        };
      } else if (g.polygon) {
        dragRef.current = {
          id: det.id,
          kind: 'region',
          startX: pt.x,
          startY: pt.y,
          base: null,
          bbox: (g.bbox ? [...g.bbox] : null) as [number, number, number, number] | null,
        };
      }
    },
    [stage, toSvgPoint],
  );

  const onMove = useCallback(
    (e: React.PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const pt = toSvgPoint(e.clientX, e.clientY);
      if (!pt) return;
      const dx = pt.x - drag.startX;
      const dy = pt.y - drag.startY;
      if (drag.kind === 'pan') {
        setView((v) => ({ ...v, x: v.x - dx, y: v.y - dy }));
        return;
      }
      if (drag.kind === 'point' && drag.base) {
        const nx = Math.round((drag.base.x + dx) * 10) / 10;
        const ny = Math.round((drag.base.y + dy) * 10) / 10;
        updateDetection(drag.id, (d) => {
          if (d.geometry.point) d.geometry.point = { x: nx, y: ny };
          if (d.geometry.bbox) {
            const hw = (drag.bbox?.[2] ?? d.geometry.bbox![2]) - (drag.bbox?.[0] ?? d.geometry.bbox![0]);
            const hh = (drag.bbox?.[3] ?? d.geometry.bbox![3]) - (drag.bbox?.[1] ?? d.geometry.bbox![1]);
            d.geometry.bbox = [nx - hw / 2, ny - hh / 2, nx + hw / 2, ny + hh / 2];
          }
        });
        return;
      }
      if (drag.kind === 'region') {
        updateDetection(drag.id, (d) => {
          if (d.geometry.polygon) d.geometry.polygon = d.geometry.polygon.map((p) => ({ x: p.x + dx, y: p.y + dy }));
          if (d.geometry.bbox) d.geometry.bbox = [d.geometry.bbox[0] + dx, d.geometry.bbox[1] + dy, d.geometry.bbox[2] + dx, d.geometry.bbox[3] + dy];
        });
      }
    },
    [toSvgPoint, updateDetection],
  );

  const endDrag = useCallback(() => {
    dragRef.current = null;
  }, []);

  const clickBackground = useCallback(
    (e: React.PointerEvent) => {
      if (stage !== 'review') return;
      const pt = toSvgPoint(e.clientX, e.clientY);
      if (placeMode && pt) {
        const id = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? `GATE_${crypto.randomUUID().slice(0, 6)}` : `GATE_${Date.now()}`;
        const x = Math.round(pt.x * 10) / 10;
        const y = Math.round(pt.y * 10) / 10;
        setDetections((prev) => [
          ...prev,
          {
            id,
            kind: 'GATE',
            geometry: { type: 'POINT', point: { x, y }, bbox: [x - 9, y - 9, x + 9, y + 9] },
            confidence: 0.5,
            source: 'USER',
            metadata: { side: 'N', width_px: 18, kind: 'ENTRY' },
          },
        ]);
        setSelectedId(id);
        setPlaceMode(false);
        return;
      }
      setSelectedId(null);
    },
    [stage, placeMode, toSvgPoint],
  );

  const focusOn = useCallback(
    (id: string) => {
      const d = detections.find((x) => x.id === id);
      if (!d) return;
      const c = centroidOf(d);
      setView((v) => ({ ...v, x: c.x - W / (2 * v.k), y: c.y - H / (2 * v.k) }));
      setSelectedId(id);
    },
    [detections, W, H],
  );

  const viewBox = useMemo(() => `${view.x} ${view.y} ${W / view.k} ${H / view.k}`, [view, W, H]);

  // ------------------------------------------------------------------ //
  //  reconstruction
  // ------------------------------------------------------------------ //
  const reconstruct = useCallback(async () => {
    if (!detection) return;
    setStage('reconstructing');
    setError(null);
    try {
      const r = await api.reconstructBlueprint({ ...detection, detections });
      if (!mountedRef.current) return;
      setResult(r);
      setStage('done');
      await refreshCatalog();
      selectVenue(r.venue.id);
    } catch (e) {
      if (!mountedRef.current) return;
      setError(e instanceof Error ? e.message : 'Reconstruction failed');
      setStage('review');
    }
  }, [detection, detections, refreshCatalog, selectVenue]);

  const gateCount = detections.filter((d) => d.kind === 'GATE').length;
  const regionCount = detections.filter((d) => d.kind === 'REGION').length;
  const wallCount = detections.filter((d) => d.kind === 'WALL').length;
  const stairCount = detections.filter((d) => d.kind === 'STAIR').length;
  const labelCount = detections.filter((d) => d.kind === 'TEXT').length;

  const selected = selectedId ? (detections.find((d) => d.id === selectedId) ?? null) : null;

  const stageIndex = stage === 'idle' ? 0 : stage === 'detecting' ? 1 : stage === 'review' ? 2 : stage === 'reconstructing' ? 3 : 3;

  return (
    <div className="flex h-full w-full flex-col bg-od-canvas">
      {/* stepper */}
      <div className="flex shrink-0 items-center gap-2 border-b border-od-line bg-od-panel px-4 py-2">
        {STEPS.map((label, i) => {
          const active = i === stageIndex || (stage === 'done' && i <= 3);
          const done = i < stageIndex;
          return (
            <div key={label} className="flex items-center gap-2">
              <span
                className={`flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-[0.16em] ${
                  active ? 'text-od-ink' : done ? 'text-od-ok' : 'text-od-muted'
                }`}
              >
                <span
                  className={`flex h-4 w-4 items-center justify-center rounded-full border ${
                    active
                      ? 'border-od-ink bg-od-ink text-od-canvas'
                      : done
                        ? 'border-od-ok text-od-ok'
                        : 'border-od-line-strong text-od-muted'
                  }`}
                >
                  {done ? <Check className="h-2.5 w-2.5" /> : i + 1}
                </span>
                {label}
              </span>
              {i < STEPS.length - 1 && <span className="h-px w-5 bg-od-line-strong" />}
            </div>
          );
        })}
        <span className="flex-1" />
        <button onClick={onExit} className="btn btn-ghost" title="Back to the workspace">
          <X className="h-3.5 w-3.5" /> Exit
        </button>
      </div>

      {/* idle upload */}
      {stage === 'idle' && (
        <div className="flex min-h-0 flex-1 items-center justify-center p-6">
          <div className="w-full max-w-md">
            <div className="flex items-center gap-2 text-[9px] uppercase tracking-[0.22em] text-od-muted">
              <FileUp className="h-3 w-3" /> Step 1 · drop a blueprint
            </div>
            <div
              role="button"
              tabIndex={0}
              aria-label="Upload a venue blueprint"
              onClick={() => fileRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') fileRef.current?.click();
              }}
              className="mt-2 flex h-44 cursor-pointer flex-col items-center justify-center gap-2 border border-dashed border-od-line-strong bg-od-panel hover:border-od-ink"
            >
              <FileUp className="h-6 w-6 text-od-ink" />
              <span className="text-[10px] uppercase tracking-[0.16em] text-od-muted">PNG / JPG / WEBP / PDF</span>
            </div>
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/bmp"
              className="hidden"
              onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
            />
            {error && (
              <p className="mt-3 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.1em] text-od-danger">
                <AlertTriangle className="h-3.5 w-3.5" /> {error}
              </p>
            )}
          </div>
        </div>
      )}

      {/* processing */}
      {stage === 'detecting' && (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3">
          <Loader2 className="h-6 w-6 animate-spin text-od-ink" />
          <span className="text-[10px] uppercase tracking-[0.24em] text-od-muted">
            Detecting walls, regions, gates, stairs, labels…
          </span>
          {error && <span className="text-[10px] uppercase tracking-[0.1em] text-od-danger">{error}</span>}
        </div>
      )}

      {/* review overlay */}
      {(stage === 'review' || stage === 'reconstructing' || stage === 'done') && detection && imageUrl && (
        <div className="flex min-h-0 flex-1">
          {/* canvas */}
          <div className="relative min-w-0 flex-1">
            <svg
              ref={svgRef}
              viewBox={viewBox}
              preserveAspectRatio="xMidYMid meet"
              role="img"
              aria-label="Blueprint detections overlay"
              className="h-full w-full touch-none select-none"
              style={{ cursor: placeMode ? 'crosshair' : 'default' }}
              onWheel={onWheel}
              onPointerMove={onMove}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
              onPointerDown={clickBackground}
            >
              <image
                href={imageUrl}
                x="0"
                y="0"
                width={W}
                height={H}
                preserveAspectRatio="none"
                style={{ opacity: 0.92 }}
              />

              {/* BOUNDARY outlines */}
              <g pointerEvents="none">
                {detections
                  .filter((d) => d.kind === 'BOUNDARY' && d.geometry.polygon)
                  .map((d) => (
                    <polygon
                      key={d.id}
                      points={d.geometry.polygon!.map((p) => `${p.x},${p.y}`).join(' ')}
                      fill="none"
                      stroke="var(--od-ink)"
                      strokeWidth={Math.max(1, W / 900)}
                      strokeOpacity={0.55}
                      strokeDasharray="6 5"
                    />
                  ))}
              </g>

              {/* REGION polygons */}
              {showRegions &&
                detections
                  .filter((d) => d.kind === 'REGION' && d.geometry.polygon)
                  .map((d) => {
                    const c = centroidOf(d);
                    const kind = regionKindOf(d);
                    const color = (kind && REGION_COLOR[kind]) || '#8d6bb3';
                    const sel = selectedId === d.id;
                    const low = d.confidence < 0.55;
                    return (
                      <g key={d.id} onPointerDown={(e) => startDrag(e, d)} style={{ cursor: 'grab' }}>
                        <polygon
                          points={d.geometry.polygon!.map((p) => `${p.x},${p.y}`).join(' ')}
                          fill={color}
                          fillOpacity={sel ? 0.28 : 0.14}
                          stroke={sel ? '#3cb879' : color}
                          strokeWidth={sel ? Math.max(2, W / 420) : Math.max(1, W / 800)}
                          strokeDasharray={low && showLowConf ? '7 5' : undefined}
                          strokeOpacity={low && showLowConf ? 0.7 : 0.9}
                        />
                        <text
                          x={c.x}
                          y={c.y}
                          textAnchor="middle"
                          fontSize={Math.max(10, W / 90)}
                          fontWeight={700}
                          fill={sel ? '#ffffff' : 'rgba(255,255,255,0.95)'}
                          stroke="rgba(0,0,0,0.55)"
                          strokeWidth={3}
                          paintOrder="stroke"
                          style={{ textTransform: 'uppercase', letterSpacing: '0.08em', pointerEvents: 'none' }}
                        >
                          {kind ?? 'ROOM'}
                          {showLowConf && low ? ` · ${pct(d.confidence)}` : ''}
                        </text>
                      </g>
                    );
                  })}

              {/* WALL segments */}
              {showWalls &&
                detections
                  .filter((d) => d.kind === 'WALL' && d.geometry.p0 && d.geometry.p1)
                  .map((d) => (
                    <line
                      key={d.id}
                      x1={d.geometry.p0!.x}
                      y1={d.geometry.p0!.y}
                      x2={d.geometry.p1!.x}
                      y2={d.geometry.p1!.y}
                      stroke={WALL_COLOR}
                      strokeWidth={Math.max(2, W / 640)}
                      strokeLinecap="round"
                      opacity={selectedId === d.id ? 1 : 0.75}
                    />
                  ))}

              {/* STAIR polygons */}
              {showRegions &&
                detections
                  .filter((d) => d.kind === 'STAIR' && d.geometry.polygon)
                  .map((d) => (
                    <polygon
                      key={d.id}
                      points={d.geometry.polygon!.map((p) => `${p.x},${p.y}`).join(' ')}
                      fill="none"
                      stroke="#8b95a1"
                      strokeWidth={Math.max(1, W / 800)}
                      strokeDasharray="4 3"
                      opacity={0.85}
                    />
                  ))}

              {/* CORRIDOR polylines */}
              {showPaths &&
                detections
                  .filter((d) => d.kind === 'CORRIDOR' && d.geometry.polyline && d.geometry.polyline.length > 1)
                  .map((d) => (
                    <polyline
                      key={d.id}
                      points={d.geometry.polyline!.map((p) => `${p.x},${p.y}`).join(' ')}
                      fill="none"
                      stroke="var(--od-ok)"
                      strokeWidth={Math.max(2, W / 500)}
                      strokeDasharray="10 6"
                      strokeLinecap="round"
                      opacity={0.6}
                    />
                  ))}

              {/* GATE markers */}
              {showGates &&
                detections
                  .filter((d) => d.kind === 'GATE' && d.geometry.point)
                  .map((d) => {
                    const p = d.geometry.point!;
                    const kind = gateKindOf(d);
                    const color = (kind && GATE_COLOR[kind]) || '#2f9e63';
                    const sel = selectedId === d.id;
                    const low = d.confidence < 0.55;
                    return (
                      <g key={d.id} onPointerDown={(e) => startDrag(e, d)} style={{ cursor: 'grab' }}>
                        <rect
                          x={p.x - 9}
                          y={p.y - 9}
                          width={18}
                          height={18}
                          transform={`rotate(45 ${p.x} ${p.y})`}
                          fill="rgba(10,12,14,0.85)"
                          stroke={sel ? '#3cb879' : color}
                          strokeWidth={sel ? 3 : 2}
                        />
                        {low && showLowConf && (
                          <circle cx={p.x} cy={p.y} r={16} fill="none" stroke="#ff5c55" strokeWidth={2} strokeDasharray="5 4" className="od-pulse" />
                        )}
                        <text
                          x={p.x}
                          y={p.y - 16}
                          textAnchor="middle"
                          fontSize={Math.max(10, W / 96)}
                          fontWeight={700}
                          fill="#ffffff"
                          stroke="rgba(0,0,0,0.6)"
                          strokeWidth={3}
                          paintOrder="stroke"
                          style={{ pointerEvents: 'none', textTransform: 'uppercase', letterSpacing: '0.06em' }}
                        >
                          {kind ?? 'GATE'} {pct(d.confidence)}
                        </text>
                      </g>
                    );
                  })}

              {/* TEXT labels */}
              {showLabels &&
                detections
                  .filter((d) => d.kind === 'TEXT' && d.text && d.geometry.bbox)
                  .map((d) => {
                    const b = d.geometry.bbox!;
                    return (
                      <g key={d.id}>
                        <rect
                          x={b[0] - 2}
                          y={b[1] - 2}
                          width={b[2] - b[0] + 4}
                          height={b[3] - b[1] + 4}
                          fill="rgba(79,195,247,0.08)"
                          stroke={TEXT_COLOR}
                          strokeWidth={1}
                          strokeDasharray="3 3"
                        />
                        <text
                          x={(b[0] + b[2]) / 2}
                          y={b[1] - 4}
                          textAnchor="middle"
                          fontSize={Math.max(9, W / 120)}
                          fill={TEXT_COLOR}
                          fontWeight={700}
                          style={{ letterSpacing: '0.06em' }}
                        >
                          {d.text}
                        </text>
                      </g>
                    );
                  })}
            </svg>

            {/* toolbar over the canvas */}
            <div className="absolute left-3 top-3 z-10 flex items-center gap-1 border border-od-line bg-od-panel">
              <button
                onClick={() => setView({ x: 0, y: 0, k: 1 })}
                title="Fit blueprint"
                className="flex items-center gap-1 px-2 py-1 text-[9px] uppercase tracking-[0.14em] font-bold text-od-muted hover:text-od-ink cursor-pointer border-r border-od-line last:border-r-0"
              >
                <RotateCcw className="h-3 w-3" /> Fit
              </button>
              <button
                onClick={() => setView((v) => ({ ...v, k: Math.min(14, v.k * 1.5) }))}
                title="Zoom in"
                className="px-2 py-1 text-[9px] font-bold text-od-muted hover:text-od-ink cursor-pointer border-r border-od-line last:border-r-0"
              >
                +
              </button>
              <button
                onClick={() => setView((v) => ({ ...v, k: Math.max(0.4, v.k / 1.5) }))}
                title="Zoom out"
                className="px-2 py-1 text-[9px] font-bold text-od-muted hover:text-od-ink cursor-pointer border-r border-od-line last:border-r-0"
              >
                −
              </button>
              <button
                onClick={() => setPlaceMode((p) => !p)}
                title="Click on the blueprint to place a gate"
                className={`flex items-center gap-1 px-2 py-1 text-[9px] uppercase tracking-[0.14em] font-bold cursor-pointer border-r border-od-line last:border-r-0 ${
                  placeMode ? 'bg-od-ink text-od-canvas' : 'text-od-muted hover:text-od-ink'
                }`}
              >
                <MousePointer2 className="h-3 w-3" /> Place gate
              </button>
            </div>

            {/* detection counts strip */}
            <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap items-center gap-x-3 gap-y-1 px-2 py-1 text-[9px] uppercase tracking-[0.14em] text-od-muted bg-od-panel/90 border border-od-line">
              <span>{gateCount} gates</span>
              <span>{regionCount} regions</span>
              <span>{wallCount} walls</span>
              <span>{stairCount} stairs</span>
              <span>{labelCount} labels</span>
              <span className="text-od-soft">drag to move · wheel to zoom</span>
            </div>

            {/* reconstructing overlay */}
            {stage === 'reconstructing' && (
              <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-od-canvas/70">
                <Loader2 className="h-6 w-6 animate-spin text-od-ink" />
                <span className="text-[10px] uppercase tracking-[0.24em] text-od-muted">
                  Reconstructing venue from corrected detections…
                </span>
              </div>
            )}

            {/* reconstruction summary (pre twin) */}
            {stage === 'done' && result && <SummaryCard result={result} onOpen={() => onOpenTwin(result)} />}
          </div>

          {/* side panel */}
          <aside className="hidden w-[300px] shrink-0 flex-col border-l border-od-line bg-od-panel md:flex">
            <div className="flex items-center gap-2 border-b border-od-line px-3 py-2">
              <Layers className="h-3.5 w-3.5 text-od-muted" />
              <span className="sec-label">Review detections</span>
              <span className="flex-1" />
              <span className="chip">
                {Math.round(((detections.length ? detections.reduce((a, d) => a + d.confidence, 0) / detections.length : 0)) * 100)}% avg
              </span>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">
              {/* layer toggles */}
              <div className="space-y-1 border-b border-od-line px-3 py-2">
                {(
                  [
                    ['Gates', showGates, setShowGates],
                    ['Regions', showRegions, setShowRegions],
                    ['Walls', showWalls, setShowWalls],
                    ['Labels', showLabels, setShowLabels],
                    ['Paths', showPaths, setShowPaths],
                    ['Low-confidence ring', showLowConf, setShowLowConf],
                  ] as const
                ).map(([label, on, set]) => (
                  <label key={label} className="flex cursor-pointer items-center gap-2 text-[9px] uppercase tracking-[0.16em] text-od-muted hover:text-od-ink">
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={(e) => set(e.target.checked)}
                      className="accent-[var(--od-ok)]"
                    />
                    {label}
                  </label>
                ))}
              </div>

              {/* detection list */}
              <div className="px-2 py-2">
                <div className="px-1 pb-1 text-[9px] uppercase tracking-[0.2em] text-od-muted">Detected elements</div>
                <div className="space-y-0.5">
                  {detections.map((d) => {
                    const color =
                      d.kind === 'GATE'
                        ? (gateKindOf(d) && GATE_COLOR[gateKindOf(d)!]) || '#2f9e63'
                        : d.kind === 'REGION'
                          ? (regionKindOf(d) && REGION_COLOR[regionKindOf(d)!]) || '#8d6bb3'
                          : d.kind === 'WALL'
                            ? WALL_COLOR
                            : d.kind === 'TEXT'
                              ? TEXT_COLOR
                              : 'var(--od-muted)';
                    const sel = selectedId === d.id;
                    return (
                      <button
                        key={d.id}
                        onClick={() => focusOn(d.id)}
                        className={`flex w-full items-center gap-2 border px-2 py-1 text-left cursor-pointer ${
                          sel ? 'border-od-ok bg-od-surface' : 'border-transparent hover:border-od-line hover:bg-od-surface'
                        }`}
                        title={`${d.kind} ${d.id} · ${pct(d.confidence)}`}
                      >
                        <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
                        <span className="min-w-0 flex-1 truncate text-[10px] font-bold uppercase tracking-[0.1em] text-od-ink">
                          {d.id.replace(/_/g, ' ')}
                        </span>
                        <span className="shrink-0 text-[9px] text-od-muted">{d.kind}</span>
                        <span className="shrink-0 text-[9px] font-bold" style={{ color: confColor(d.confidence) }}>
                          {pct(d.confidence)}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* selected editor */}
            <div className="border-t border-od-line px-3 py-2.5">
              {selected ? (
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[10px] font-bold uppercase tracking-[0.12em] text-od-ink">
                      {selected.id.replace(/_/g, ' ')}
                    </span>
                    <span className="chip">{selected.kind}</span>
                  </div>

                  {selected.kind === 'GATE' && (
                    <>
                      <div className="space-y-1">
                        <div className="text-[9px] uppercase tracking-[0.18em] text-od-muted">Gate type</div>
                        <div className="flex gap-1">
                          {Object.keys(GATE_COLOR).map((k) => (
                            <button
                              key={k}
                              onClick={() => updateDetection(selected.id, (d) => void (d.metadata.kind = k))}
                              className={`flex-1 border px-1 py-1 text-[9px] font-bold uppercase tracking-[0.08em] cursor-pointer ${
                                gateKindOf(selected) === k
                                  ? 'border-od-ink bg-od-ink text-od-canvas'
                                  : 'border-od-line-strong text-od-muted hover:text-od-ink'
                              }`}
                            >
                              {k === 'EMERGENCY_EXIT' ? 'EMERGENCY' : k}
                            </button>
                          ))}
                        </div>
                        <div className="pt-1">
                          <div className="pb-1 text-[9px] uppercase tracking-[0.18em] text-od-muted">Label (optional)</div>
                          <input
                            className="field w-full text-[11px]"
                            placeholder="e.g. GATE B"
                            value={String(selected.metadata?.label ?? '')}
                            onChange={(e) => updateDetection(selected.id, (d) => void (d.metadata.label = e.target.value))}
                          />
                        </div>
                      </div>
                    </>
                  )}

                  {selected.kind === 'REGION' && (
                    <div className="space-y-1">
                      <div className="text-[9px] uppercase tracking-[0.18em] text-od-muted">Region type</div>
                      <div className="flex flex-wrap gap-1">
                        {Object.keys(REGION_COLOR).map((k) => (
                          <button
                            key={k}
                            onClick={() => updateDetection(selected.id, (d) => void (d.metadata.kind = k))}
                            className={`flex-1 border px-1 py-1 text-[9px] font-bold uppercase tracking-[0.06em] cursor-pointer ${
                              regionKindOf(selected) === k
                                ? 'border-od-ink bg-od-ink text-od-canvas'
                                : 'border-od-line-strong text-od-muted hover:text-od-ink'
                            }`}
                          >
                            {k}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-[9px] uppercase tracking-[0.18em] text-od-muted">Confidence</span>
                      <span className="text-[10px] font-bold" style={{ color: confColor(selected.confidence) }}>
                        {pct(selected.confidence)}
                      </span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={Math.round(selected.confidence * 100)}
                      onChange={(e) =>
                        updateDetection(selected.id, (d) => void (d.confidence = Number(e.target.value) / 100))
                      }
                      className="w-full accent-[var(--od-ok)]"
                      aria-label="Confidence"
                    />
                  </div>

                  <div className="flex items-center justify-between gap-2 text-[9px] uppercase tracking-[0.14em] text-od-muted">
                    <span>
                      {Math.round(centroidOf(selected).x)}, {Math.round(centroidOf(selected).y)} px
                    </span>
                    <button
                      onClick={() => deleteDetection(selected.id)}
                      className="flex items-center gap-1 border border-od-danger px-1.5 py-0.5 font-bold text-od-danger cursor-pointer hover:bg-od-danger-soft"
                      aria-label="Delete detection"
                    >
                      <Trash2 className="h-3 w-3" /> Delete
                    </button>
                  </div>
                </div>
              ) : (
                <div className="text-[9px] uppercase tracking-[0.16em] leading-relaxed text-od-muted">
                  Select a detection on the blueprint or in the list to move, retype, or delete it.
                </div>
              )}

              {/* actions */}
              <div className="mt-3 flex gap-1.5">
                <button onClick={addGate} className="btn btn-ghost flex-1" title="Add a gate at the centre, then drag it into place">
                  <Plus className="h-3.5 w-3.5" /> Add gate
                </button>
                <button
                  onClick={() => void reconstruct()}
                  disabled={detections.length === 0}
                  className="btn btn-solid flex-1"
                  title="Re-run semantic + spatial + navigation with the corrected detections"
                >
                  <Wand2 className="h-3.5 w-3.5" /> Reconstruct
                </button>
              </div>
              {error && (
                <p className="mt-2 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.1em] text-od-danger">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0" /> {error}
                </p>
              )}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
//  Reconstruction summary card (shown over the canvas before the twin opens)
// --------------------------------------------------------------------------- //
function SummaryCard({ result, onOpen }: { result: BlueprintResult; onOpen: () => void }) {
  const report: ReconstructionReport | null = result.report ?? null;
  const gates = result.venue.nodes.filter((n) => ['ENTRY', 'EXIT', 'EMERGENCY_EXIT'].includes(n.type)).length;
  const openings = result.spatial?.openings.length ?? 0;
  const structures = result.spatial?.structures.length ?? 0;
  const paths = result.spatial?.paths.length ?? 0;
  const review = (report?.elements ?? []).filter((e) => e.status === 'REVIEW' || e.status === 'REJECTED');
  const warnings = report?.warnings ?? [];
  const unresolved = report?.unresolved ?? [];

  return (
    <div className="absolute left-1/2 top-1/2 z-30 w-[380px] max-w-[calc(100%-1rem)] -translate-x-1/2 -translate-y-1/2 border border-od-line bg-od-panel shadow-[0_32px_80px_-32px_rgba(0,0,0,0.85)]">
      <div className="flex items-center justify-between border-b border-od-line px-4 py-3">
        <div>
          <div className="sec-label">Venue reconstructed</div>
          <div className="mt-0.5 font-display text-[13px] font-extrabold uppercase tracking-[0.08em] text-od-ink">
            {result.venue.name.replace(/_/g, ' ')}
          </div>
        </div>
        <span className={`chip ${result.degraded ? 'is-warn' : 'is-active'}`}>
          <span className={`status-dot ${result.degraded ? 'is-warn' : 'is-ok'}`} />
          {result.degraded ? 'degraded' : 'full'}
        </span>
      </div>

      <div className="px-4 py-3">
        <div className="flex items-end justify-between gap-2">
          <span className="text-[9px] uppercase tracking-[0.2em] text-od-muted">Overall confidence</span>
          <span className="num text-[16px] font-extrabold" style={{ color: confColor(result.confidence) }}>
            {Math.round(result.confidence * 100)}%
          </span>
        </div>

        <div className="mt-3 grid grid-cols-3 gap-px bg-od-line text-center">
          {(
            [
              ['Gates', gates],
              ['Openings', openings],
              ['Structures', structures],
              ['Paths', paths],
              ['Nodes', result.venue.nodes.length],
              ['Walkways', result.venue.edges.length],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="bg-od-panel px-2 py-2">
              <div className="num text-[14px] font-extrabold text-od-ink">{value}</div>
              <div className="text-[8px] uppercase tracking-[0.16em] text-od-muted">{label}</div>
            </div>
          ))}
        </div>

        {(review.length > 0 || warnings.length > 0 || unresolved.length > 0) && (
          <div className="mt-3 space-y-1 border border-od-warn/60 bg-od-warn-soft px-3 py-2">
            <div className="flex items-center gap-1.5 text-[9px] uppercase tracking-[0.18em] font-bold text-od-warn">
              <AlertTriangle className="h-3 w-3" /> Review / uncertain areas
            </div>
            {review.length > 0 && (
              <div className="text-[10px] leading-relaxed text-od-soft">
                {review.length} element{review.length === 1 ? '' : 's'} flagged for review
                {review.slice(0, 3).map((e) => ` · ${e.id}`)}
              </div>
            )}
            {warnings.slice(0, 3).map((w) => (
              <div key={w} className="text-[10px] leading-relaxed text-od-soft">
                · {w}
              </div>
            ))}
            {unresolved.slice(0, 3).map((u) => (
              <div key={u} className="text-[10px] leading-relaxed text-od-soft">
                · {u}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-od-line px-4 py-3">
        <span className="text-[9px] uppercase tracking-[0.16em] text-od-muted">Reconstruction complete — twin ready</span>
        <button onClick={onOpen} className="btn btn-solid">
          OPEN 3D TWIN <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
