import { useCallback, useEffect, useRef, useState } from 'react';
import { MousePointer2, Save, SquarePlus, Trash2, Upload, Waypoints } from 'lucide-react';
import { api } from '../lib/api';
import type { EdgeModel, NodeModel, NodeType, VenueModel } from '../lib/types';
import { useSimulation } from '../store/SimulationContext';

const NODE_TYPES: NodeType[] = [
  'ENTRY',
  'EXIT',
  'EMERGENCY_EXIT',
  'INTERSECTION',
  'CONCESSION',
  'CHECKPOINT',
  'ZONE',
];

const TYPE_HINT: Record<NodeType, string> = {
  ENTRY: 'entry gate',
  EXIT: 'exit',
  EMERGENCY_EXIT: 'emergency exit',
  INTERSECTION: 'junction',
  CONCESSION: 'concession point',
  CHECKPOINT: 'checkpoint',
  ZONE: 'standing zone',
};

const NEW_NODE_CAPACITY: Record<NodeType, number | null> = {
  ENTRY: 120,
  EXIT: 200,
  EMERGENCY_EXIT: 400,
  INTERSECTION: null,
  CONCESSION: 200,
  CHECKPOINT: 150,
  ZONE: 800,
};

let counter = 0;
function freshId(type: NodeType): string {
  counter += 1;
  const prefix = { ENTRY: 'G', EXIT: 'X', EMERGENCY_EXIT: 'EX', INTERSECTION: 'N', CONCESSION: 'C', CHECKPOINT: 'K', ZONE: 'Z' }[type];
  return `${prefix}${String(counter).padStart(2, '0')}`;
}

type Tool = 'select' | 'add' | 'connect';

interface BuilderProps {
  venue: VenueModel;
  onChange: (v: VenueModel) => void;
}

function Builder({ venue, onChange }: BuilderProps) {
  const [tool, setTool] = useState<Tool>('select');
  const [type, setType] = useState<NodeType>('INTERSECTION');
  const [selected, setSelected] = useState<string | null>(null);
  const [connectFrom, setConnectFrom] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const edgeKey = (e: EdgeModel) => `${e.source}→${e.destination}`;

  const nodeById = useCallback(
    (id: string | null) => venue.nodes.find((n) => n.id === id) ?? null,
    [venue.nodes],
  );
  const edgeAt = useCallback(
    (id: string) => venue.edges.find((e) => edgeKey(e) === id) ?? null,
    [venue.edges],
  );

  const toVenueCoords = useCallback(
    (clientX: number, clientY: number) => {
      const svg = svgRef.current!;
      const pt = svg.createSVGPoint();
      pt.x = clientX;
      pt.y = clientY;
      const ctm = svg.getScreenCTM();
      if (!ctm) return { x: 50, y: 50 };
      const p = pt.matrixTransform(ctm.inverse());
      return {
        x: Math.min(venue.width - 10, Math.max(10, Math.round(p.x))),
        y: Math.min(venue.height - 10, Math.max(10, Math.round(p.y))),
      };
    },
    [venue.width, venue.height],
  );

  const addNode = useCallback(
    (pos: { x: number; y: number }) => {
      const node: NodeModel = {
        id: freshId(type),
        position: pos,
        type,
        capacity: NEW_NODE_CAPACITY[type],
        area_m2: type === 'ZONE' ? 900 : null,
        metadata: {},
      };
      onChange({ ...venue, nodes: [...venue.nodes, node] });
      setSelected(node.id);
    },
    [type, venue, onChange],
  );

  const moveNode = useCallback(
    (id: string, pos: { x: number; y: number }) => {
      onChange({
        ...venue,
        nodes: venue.nodes.map((n) => (n.id === id ? { ...n, position: pos } : n)),
      });
    },
    [venue, onChange],
  );

  const connect = useCallback(
    (a: string, b: string) => {
      if (a === b) return;
      if (venue.edges.some((e) => e.source === a && e.destination === b)) return;
      const edge: EdgeModel = {
        id: `${a}→${b}`,
        source: a,
        destination: b,
        length_m: 40,
        width_m: 3,
        capacity: 120,
        is_open: true,
        is_emergency: false,
      };
      onChange({ ...venue, edges: [...venue.edges, edge] });
    },
    [venue, onChange],
  );

  const updateNode = useCallback(
    (id: string, patch: Partial<NodeModel>) => {
      onChange({
        ...venue,
        nodes: venue.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)),
      });
    },
    [venue, onChange],
  );

  const updateEdge = useCallback(
    (key: string, patch: Partial<EdgeModel>) => {
      onChange({
        ...venue,
        edges: venue.edges.map((e) => (edgeKey(e) === key ? { ...e, ...patch } : e)),
      });
    },
    [venue, onChange],
  );

  const deleteNode = useCallback(
    (id: string) => {
      const node = nodeById(id);
      if (!node) return;
      if (node.type === 'ENTRY' && venue.nodes.filter((n) => n.type === 'ENTRY').length === 1) return;
      onChange({
        ...venue,
        nodes: venue.nodes.filter((n) => n.id !== id),
        edges: venue.edges.filter((e) => e.source !== id && e.destination !== id),
      });
      setSelected(null);
    },
    [venue, nodeById, onChange],
  );

  const deleteEdge = useCallback(
    (key: string) => {
      onChange({ ...venue, edges: venue.edges.filter((e) => edgeKey(e) !== key) });
      setSelected(null);
    },
    [venue, onChange],
  );

  const onCanvasClick = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (tool !== 'add') return;
      addNode(toVenueCoords(e.clientX, e.clientY));
    },
    [tool, addNode, toVenueCoords],
  );

  const onNodeClick = useCallback(
    (e: React.MouseEvent, id: string) => {
      e.stopPropagation();
      if (tool === 'connect') {
        if (!connectFrom) {
          setConnectFrom(id);
        } else if (connectFrom !== id) {
          connect(connectFrom, id);
          setConnectFrom(null);
        } else {
          setConnectFrom(null);
        }
        return;
      }
      if (tool === 'add') return;
      setSelected(id);
    },
    [tool, connectFrom, connect],
  );

  const onNodeDrag = useCallback(
    (e: React.PointerEvent<SVGGElement>, id: string) => {
      e.stopPropagation();
      if (tool !== 'select') return;
      const svg = svgRef.current!;
      const move = (ev: PointerEvent) => {
        moveNode(id, toVenueCoords(ev.clientX, ev.clientY));
      };
      const up = () => {
        svg.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
      };
      svg.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    },
    [tool, moveNode, toVenueCoords],
  );

  const selectedNode = nodeById(selected);
  const selectedEdge = edgeAt(selected ?? '');
  const selIsNode = selected != null && selectedNode != null;

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_280px] gap-lg items-start">
      <div className="border border-outline-variant bg-surface-container-lowest relative overflow-hidden">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${venue.width} ${venue.height}`}
          className="w-full h-[56vh] min-h-[420px] cursor-crosshair"
          style={{ touchAction: 'none' }}
          onClick={onCanvasClick}
          role="img"
          aria-label="Venue graph editor canvas"
        >
          <rect width={venue.width} height={venue.height} fill="#f9f9f9" />
          {/* grid pattern */}
          <pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse">
            <path d="M 50 0 L 0 0 0 50" fill="none" stroke="#e2e2e2" strokeWidth="0.6" />
          </pattern>
          <rect width={venue.width} height={venue.height} fill="url(#grid)" />

          {venue.edges.map((e) => {
            const a = nodeById(e.source);
            const b = nodeById(e.destination);
            if (!a || !b) return null;
            const active = edgeKey(e) === selected;
            return (
              <g
                key={edgeKey(e)}
                onClick={(ev) => {
                  ev.stopPropagation();
                  setSelected(edgeKey(e));
                  setConnectFrom(null);
                }}
                className="cursor-pointer"
                style={{ pointerEvents: 'stroke' }}
              >
                <line
                  x1={a.position.x}
                  y1={a.position.y}
                  x2={b.position.x}
                  y2={b.position.y}
                  stroke={!e.is_open ? '#ff291a' : '#000000'}
                  strokeWidth={active ? 3 : e.is_emergency ? 2.4 : 1.6}
                  strokeDasharray={!e.is_open ? '5 4' : undefined}
                  strokeOpacity={0.75}
                />
                {active && (
                  <circle
                    cx={(a.position.x + b.position.x) / 2}
                    cy={(a.position.y + b.position.y) / 2}
                    r={4}
                    fill="#ff291a"
                    pointerEvents="none"
                  />
                )}
              </g>
            );
          })}

          {venue.nodes.map((n) => {
            const active = selectedNode?.id === n.id;
            const r = n.type === 'ZONE' ? 16 : 8;
            const stroke = n.type === 'EMERGENCY_EXIT' ? '#c25700' : '#000000';
            return (
              <g
                key={n.id}
                transform={`translate(${n.position.x},${n.position.y})`}
                onClick={(e) => onNodeClick(e, n.id)}
                onPointerDown={(e) => onNodeDrag(e, n.id)}
                className="cursor-pointer"
              >
                {active && <circle r={r + 4} fill="none" stroke="#ff291a" strokeWidth={1.2} />}
                {n.type === 'ENTRY' && (
                  <rect x={-r} y={-r} width={r * 2} height={r * 2} fill="#ffffff" stroke={stroke} strokeWidth={1.6} />
                )}
                {n.type === 'EXIT' && (
                  <path d={`M${-r},${-r} L${r},0 L${-r},${r} Z`} fill="#ffffff" stroke={stroke} strokeWidth={1.6} />
                )}
                {n.type === 'EMERGENCY_EXIT' && (
                  <path d={`M0,${-r} L${r},0 L0,${r} L${-r},0 Z`} fill="#ffffff" stroke={stroke} strokeWidth={1.8} />
                )}
                {n.type === 'CONCESSION' && (
                  <circle r={r} fill="#ffffff" stroke={stroke} strokeWidth={1.6} />
                )}
                {n.type === 'CHECKPOINT' && (
                  <circle r={r} fill="#ffffff" stroke={stroke} strokeWidth={1.6} strokeDasharray="3 2" />
                )}
                {n.type === 'INTERSECTION' && (
                  <rect x={-r * 0.6} y={-r * 0.6} width={r * 1.2} height={r * 1.2} fill="#ffffff" stroke={stroke} strokeWidth={1.4} />
                )}
                {n.type === 'ZONE' && (
                  <rect x={-r * 1.1} y={-r * 1.1} width={r * 2.2} height={r * 2.2} fill="#eeeeee" stroke={stroke} strokeWidth={1.4} />
                )}
                <text
                  y={r + 16}
                  textAnchor="middle"
                  fontSize="8"
                  fill="#5d5f5f"
                  fontWeight={700}
                >
                  {n.id}
                </text>
              </g>
            );
          })}
        </svg>

        <div className="absolute top-2 left-2 flex gap-xs bg-surface-container-lowest/90 border border-outline-variant px-sm py-xs">
          {(
            [
              { id: 'select', label: 'Select/Drag', icon: MousePointer2 },
              { id: 'add', label: `Add ${TYPE_HINT[type]}`, icon: SquarePlus },
              { id: 'connect', label: connectFrom ? `To: ${connectFrom}` : 'Connect', icon: Waypoints },
            ] as { id: Tool; label: string; icon: typeof MousePointer2 }[]
          ).map((t) => (
            <button
              key={t.id}
              onClick={() => {
                setTool(t.id);
                setConnectFrom(null);
              }}
              className={`px-sm py-xs text-[9px] uppercase tracking-[0.16em] font-bold flex items-center gap-xs cursor-pointer transition-none border ${
                tool === t.id
                  ? 'bg-primary text-background border-primary'
                  : 'border-outline-variant text-primary hover:bg-primary hover:text-background'
              }`}
            >
              <t.icon className="w-3 h-3" />
              {t.label}
            </button>
          ))}
        </div>

        <div className="absolute top-2 right-2 flex gap-xs bg-surface-container-lowest/90 border border-outline-variant px-sm py-xs">
          {NODE_TYPES.map((t) => (
            <button
              key={t}
              onClick={() => {
                setType(t);
                setTool('add');
              }}
              className={`px-sm py-xs text-[9px] uppercase tracking-[0.14em] font-bold cursor-pointer transition-none border ${
                type === t && tool === 'add'
                  ? 'bg-primary text-background border-primary'
                  : 'border-outline-variant text-primary hover:bg-primary hover:text-background'
              }`}
            >
              {t.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
      </div>

      {/* inspector */}
      <div className="space-y-lg">
        <div className="border border-outline-variant">
          <div className="px-md py-sm bg-surface-container-low grid-line-bottom text-[10px] font-bold uppercase tracking-[0.2em]">
            Inspector
          </div>
          {!selected && (
            <div className="px-md py-md text-[10px] uppercase tracking-[0.16em] text-secondary leading-relaxed">
              Select a node or walkway to edit its properties.
            </div>
          )}
          {selIsNode && selectedNode && (
            <div className="px-md py-md space-y-md">
              <div className="flex items-center justify-between gap-md">
                <span className="text-[10px] uppercase tracking-[0.16em] text-secondary">Node</span>
                <span className="text-[11px] font-bold">{selectedNode.id}</span>
              </div>
              <div className="flex items-center gap-sm">
                <span className="text-[10px] uppercase tracking-[0.16em] text-secondary flex-1">Type</span>
                <select
                  value={selectedNode.type}
                  onChange={(e) => updateNode(selectedNode.id, { type: e.target.value as NodeType })}
                  className="bg-background border border-primary px-sm py-xs text-[10px] font-bold uppercase tracking-widest cursor-pointer"
                >
                  {NODE_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.16em] text-secondary">
                Capacity (p/min)
                <input
                  type="number"
                  value={selectedNode.capacity ?? ''}
                  placeholder="—"
                  onChange={(e) =>
                    updateNode(selectedNode.id, {
                      capacity: e.target.value === '' ? null : Number(e.target.value),
                    })
                  }
                  className="flex-1 bg-background border border-primary px-sm py-xs text-[11px] font-bold mono-tabular"
                />
              </label>
              <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.16em] text-secondary">
                Area m² (ZONE)
                <input
                  type="number"
                  value={selectedNode.area_m2 ?? ''}
                  placeholder="—"
                  onChange={(e) =>
                    updateNode(selectedNode.id, {
                      area_m2: e.target.value === '' ? null : Number(e.target.value),
                    })
                  }
                  className="flex-1 bg-background border border-primary px-sm py-xs text-[11px] font-bold mono-tabular"
                />
              </label>
              <div className="flex gap-sm">
                <button
                  onClick={() => deleteNode(selectedNode.id)}
                  className="btn-outline flex-1 text-error"
                  style={{ borderColor: 'currentColor' }}
                >
                  <Trash2 className="w-3.5 h-3.5" /> Delete node
                </button>
              </div>
            </div>
          )}
          {!selIsNode && selectedEdge && (
            <div className="px-md py-md space-y-md">
              <div className="flex items-center justify-between gap-md">
                <span className="text-[10px] uppercase tracking-[0.16em] text-secondary">Walkway</span>
                <span className="text-[11px] font-bold mono-tabular">{selected}</span>
              </div>
              <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.16em] text-secondary">
                Width (m)
                <input
                  type="number"
                  step="0.5"
                  value={selectedEdge.width_m}
                  onChange={(e) => updateEdge(selected!, { width_m: Number(e.target.value) })}
                  className="flex-1 bg-background border border-primary px-sm py-xs text-[11px] font-bold mono-tabular"
                />
              </label>
              <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.16em] text-secondary">
                Capacity (p/min)
                <input
                  type="number"
                  value={selectedEdge.capacity}
                  onChange={(e) => updateEdge(selected!, { capacity: Number(e.target.value) })}
                  className="flex-1 bg-background border border-primary px-sm py-xs text-[11px] font-bold mono-tabular"
                />
              </label>
              <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.16em] text-secondary cursor-pointer">
                <input
                  type="checkbox"
                  checked={selectedEdge.is_open}
                  onChange={(e) => updateEdge(selected!, { is_open: e.target.checked })}
                  className="w-3.5 h-3.5 accent-black"
                />
                Walkway open
              </label>
              <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.16em] text-secondary cursor-pointer">
                <input
                  type="checkbox"
                  checked={selectedEdge.is_emergency}
                  onChange={(e) => updateEdge(selected!, { is_emergency: e.target.checked })}
                  className="w-3.5 h-3.5 accent-black"
                />
                Emergency corridor
              </label>
              <button
                onClick={() => deleteEdge(selected!)}
                className="btn-outline text-error w-full"
                style={{ borderColor: 'currentColor' }}
              >
                <Trash2 className="w-3.5 h-3.5" /> Delete walkway
              </button>
            </div>
          )}
        </div>

        <div className="flex items-center gap-sm px-md py-sm border border-outline-variant text-[10px] uppercase tracking-[0.16em] text-secondary">
          <span>{venue.nodes.length} nodes</span>
          <span>·</span>
          <span>{venue.edges.length} walkways</span>
        </div>
      </div>
    </div>
  );
}

export default function VenueBuilderView() {
  const { venues, refreshCatalog } = useSimulation();
  const [draft, setDraft] = useState<VenueModel | null>(null);
  const [source, setSource] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!draft && venues.length > 0) {
      const v = venues[0];
      setDraft(v);
      setSource(v.id);
    }
  }, [venues, draft]);

  const importBlueprint = useCallback(
    async (file: File) => {
      setImporting(true);
      setNotice(null);
      try {
        const result = await api.importBlueprint(file);
        setDraft({ ...result.venue });
        setSource(result.venue.id);
        await refreshCatalog();
        const level =
          result.degradation_level === 0
            ? 'full'
            : result.degradation_level === 1
              ? 'geometry-only'
              : result.degradation_level === 2
                ? 'heuristic'
                : 'template';
        const flagged = result.degraded ? ` — degraded (${level})` : '';
        const notes = result.notes.length ? ` ${result.notes.join(' ')}` : '';
        setNotice(
          `Imported '${result.venue.name}': ${result.venue.nodes.length} nodes, ` +
            `${result.venue.edges.length} walkways, confidence ${Math.round(result.confidence * 100)}%${flagged}.${notes}`,
        );
      } catch (e) {
        setNotice(e instanceof Error ? e.message : 'Blueprint import failed');
      } finally {
        setImporting(false);
        if (fileRef.current) fileRef.current.value = '';
      }
    },
    [refreshCatalog],
  );

  const save = useCallback(async () => {
    if (!draft) return;
    setSaving(true);
    setNotice(null);
    try {
      const existing = venues.find((v) => v.id === draft.id);
      const saved = existing ? await api.saveVenue(draft) : await api.createVenue(draft);
      setDraft(saved);
      setNotice(`Venue '${saved.id}' saved — back in the catalogue.`);
      await refreshCatalog();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  }, [draft, venues, refreshCatalog]);

  return (
    <div className="space-y-lg">
      <div className="flex flex-wrap items-center gap-md">
        <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.2em] text-secondary">
          Load venue
          <select
            value={source}
            onChange={(e) => {
              const v = venues.find((x) => x.id === e.target.value) ?? draft;
              if (v) {
                setDraft({ ...v });
                setSource(v.id);
              }
            }}
            className="bg-background border border-primary px-md py-sm text-[11px] font-bold uppercase tracking-widest cursor-pointer"
          >
            {venues.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} ({v.id})
              </option>
            ))}
          </select>
        </label>
        <button
          onClick={() => {
            counter = 0;
            const id = `VENUE_${String(Date.now()).slice(-6)}`;
            setDraft({
              id,
              name: `Untitled venue ${id}`,
              width: 1000,
              height: 620,
              nodes: [],
              edges: [],
            });
            setSource(id);
            setNotice(null);
          }}
          className="btn-outline"
        >
          <SquarePlus className="w-3.5 h-3.5" /> New venue
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/bmp"
          className="hidden"
          aria-label="Upload venue blueprint image"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void importBlueprint(file);
          }}
        />
        <button onClick={() => fileRef.current?.click()} disabled={importing} className="btn-outline">
          <Upload className="w-3.5 h-3.5" />
          {importing ? 'Importing…' : 'Import blueprint'}
        </button>
        <div className="ml-auto flex items-center gap-md">
          {notice && <span className="text-[10px] uppercase tracking-[0.14em] font-bold text-error">{notice}</span>}
          <button onClick={save} disabled={saving || !draft} className="btn-primary">
            <Save className="w-3.5 h-3.5" /> {saving ? 'Saving…' : 'Save venue'}
          </button>
        </div>
      </div>

      {!draft ? (
        <div className="border border-outline-variant px-md py-xl text-[11px] uppercase tracking-[0.16em] text-secondary">
          No venues found in the catalogue.
        </div>
      ) : (
        <Builder venue={draft} onChange={(v) => setDraft(v)} />
      )}
      <div className="text-[10px] uppercase tracking-[0.14em] text-secondary leading-relaxed">
        Tip: every venue must contain at least one ENTRY and one EXIT / EMERGENCY_EXIT, stay
        connected, and validate on save. A deliberately narrow corridor makes bottlenecks easy to
        reproduce.
      </div>
    </div>
  );
}