import { useCallback, useEffect, useState } from 'react';
import { Play, Plus, Save, Trash2 } from 'lucide-react';
import { api } from '../lib/api';
import type { EventPhaseModel, EventPhaseName, ScenarioModel } from '../lib/types';
import { useSimulation } from '../store/SimulationContext';

const PHASE_NAMES: EventPhaseName[] = ['ENTRY', 'PEAK', 'INTERVAL', 'EXIT_SURGE'];

function DistEditor({
  title,
  value,
  options,
  onChange,
}: {
  title: string;
  value: Record<string, number>;
  options: { id: string; label: string }[];
  onChange: (v: Record<string, number>) => void;
}) {
  const set = (id: string, v: number) => onChange({ ...value, [id]: v });
  const total = Object.values(value).reduce((a, b) => a + b, 0);
  const ok = Math.abs(total - 1) < 1e-6 && Object.keys(value).length > 0;

  return (
    <div className="blk">
      <div className="blk-hd">
        <span className="sec-label">{title}</span>
        <span className={`chip ${ok ? 'is-ok' : 'is-danger'} mono-tabular`}>
          Σ {total.toFixed(3)}
        </span>
      </div>
      <div className="space-y-2 px-4 py-3">
        {options.map((o) => {
          const share = value[o.id] ?? 0;
          return (
            <label key={o.id} className="block">
              <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.12em] text-od-muted">
                <span className="w-24 truncate" title={o.label}>{o.label}</span>
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={share}
                  onChange={(e) => set(o.id, Math.max(0, Number(e.target.value)))}
                  className="field flex-1 !py-1 text-[11px] font-bold mono-tabular"
                />
                <span className="num w-10 text-right text-od-soft">{Math.round(share * 100)}%</span>
              </div>
              <div className="mt-1 ml-0 h-0.5 w-full bg-od-line">
                <div
                  className="h-full bg-od-ink transition-[width] duration-200"
                  style={{ width: `${Math.min(100, share * 100)}%` }}
                />
              </div>
            </label>
          );
        })}
        <button
          onClick={() => {
            const keys = Object.keys(value);
            const k = keys.length || options.length;
            const share = 1 / (k || 1);
            onChange(Object.fromEntries(options.map((o) => [o.id, share])));
          }}
          className="text-[9px] uppercase tracking-[0.18em] text-od-muted underline underline-offset-4 cursor-pointer transition-colors hover:text-od-ink"
        >
          Equalize
        </button>
      </div>
    </div>
  );
}

function FieldRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex items-center gap-3 text-[10px] uppercase tracking-[0.12em] text-od-muted">
      <span className="w-32 shrink-0">{label}</span>
      {children}
    </label>
  );
}

function PhaseEditor({
  phases,
  onChange,
}: {
  phases: EventPhaseModel[];
  onChange: (p: EventPhaseModel[]) => void;
}) {
  const set = (i: number, patch: Partial<EventPhaseModel>) =>
    onChange(phases.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  return (
    <div className="blk">
      <div className="blk-hd">
        <span className="sec-label">Event phases</span>
        {phases.length < 6 && (
          <button
            onClick={() =>
              onChange([
                ...phases,
                {
                  name: 'INTERVAL',
                  start_minute: 0,
                  end_minute: 60,
                  arrival_rate_multiplier: 1,
                  spawn: null,
                },
              ])
            }
            className="btn btn-ghost !px-2 !py-1"
          >
            <Plus className="h-3 w-3" /> Add phase
          </button>
        )}
      </div>
      <ul className="divide-y divide-od-line">
        {phases.map((p, i) => (
          <li key={i} className="space-y-2.5 px-4 py-3">
            <div className="flex items-center gap-2">
              <select
                value={p.name}
                onChange={(e) => set(i, { name: e.target.value as EventPhaseName })}
                className="field !py-1 text-[10px] font-bold uppercase tracking-widest cursor-pointer"
              >
                {PHASE_NAMES.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
              <span className="num text-[9px] uppercase tracking-[0.14em] text-od-muted">
                {p.start_minute}–{p.end_minute} min
              </span>
              <button
                onClick={() => onChange(phases.filter((_, j) => j !== i))}
                aria-label={`Remove phase ${i + 1}`}
                className="ml-auto btn btn-ghost !px-2 !py-1 text-od-danger hover:!text-od-danger"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <FieldRow label="Start">
                <input
                  type="number"
                  min={0}
                  value={p.start_minute}
                  onChange={(e) => set(i, { start_minute: Math.max(0, Number(e.target.value)) })}
                  className="field w-full !py-1 text-[11px] font-bold mono-tabular"
                />
              </FieldRow>
              <FieldRow label="End">
                <input
                  type="number"
                  min={0}
                  value={p.end_minute}
                  onChange={(e) => set(i, { end_minute: Math.max(1, Number(e.target.value)) })}
                  className="field w-full !py-1 text-[11px] font-bold mono-tabular"
                />
              </FieldRow>
              <FieldRow label="Arrival ×">
                <input
                  type="number"
                  min={0}
                  step={0.1}
                  value={p.arrival_rate_multiplier}
                  onChange={(e) => set(i, { arrival_rate_multiplier: Math.max(0, Number(e.target.value)) })}
                  className="field w-full !py-1 text-[11px] font-bold mono-tabular"
                />
              </FieldRow>
            </div>
            {p.name === 'EXIT_SURGE' && (
              <FieldRow label="Spawn mode">
                <select
                  value={p.spawn ?? ''}
                  onChange={(e) =>
                    set(i, { spawn: e.target.value === '' ? null : e.target.value })
                  }
                  className="field flex-1 !py-1 text-[10px] font-bold uppercase tracking-widest cursor-pointer"
                >
                  <option value="">from arrivals</option>
                  <option value="EXIT_SURGE">seated crowd leaves</option>
                  <option value="EVACUATION">evacuation</option>
                </select>
              </FieldRow>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function ScenarioBuilderView() {
  const { scenarios, venues, selectScenario, runSimulation, busy, refreshCatalog } = useSimulation();
  const [draft, setDraft] = useState<ScenarioModel | null>(null);
  const [source, setSource] = useState('');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [noticeTone, setNoticeTone] = useState<'ok' | 'err'>('ok');

  useEffect(() => {
    if (!draft && scenarios.length > 0) {
      setDraft(scenarios[0]);
      setSource(scenarios[0].id);
    }
  }, [scenarios, draft]);

  const venueById = useCallback(
    (id: string) => venues.find((v) => v.id === id) ?? null,
    [venues],
  );

  const save = useCallback(async () => {
    if (!draft) return;
    setSaving(true);
    setNotice(null);
    try {
      const existing = scenarios.find((s) => s.id === draft.id);
      const saved = existing ? await api.saveScenario(draft) : await api.createScenario(draft);
      setDraft(saved);
      setNotice(`Scenario '${saved.id}' saved.`);
      setNoticeTone('ok');
      await refreshCatalog();
      await selectScenario(saved.id);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Save failed');
      setNoticeTone('err');
    } finally {
      setSaving(false);
    }
  }, [draft, scenarios, selectScenario, refreshCatalog]);

  if (!draft) {
    return (
      <div className="blk px-4 py-10 text-center text-[11px] uppercase tracking-[0.16em] text-od-muted">
        No scenarios found in the catalogue.
      </div>
    );
  }

  const venue = venueById(draft.venue_id) ?? null;
  const set = (patch: Partial<ScenarioModel>) => setDraft({ ...draft, ...patch });

  const gates = venue?.nodes.filter((n) => n.type === 'ENTRY') ?? [];
  const exits = venue?.nodes.filter((n) => n.type === 'EXIT' || n.type === 'EMERGENCY_EXIT') ?? [];
  const destinations = venue?.nodes.filter(
    (n) => n.type === 'ZONE' || n.type === 'CONCESSION' || n.type === 'CHECKPOINT',
  ) ?? [];

  const runnable = Object.keys(draft.gate_distribution).length > 0;

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <FieldRow label="Load scenario">
          <select
            value={source}
            onChange={(e) => {
              const s = scenarios.find((x) => x.id === e.target.value) ?? draft;
              if (s) {
                setDraft({ ...s });
                setSource(s.id);
              }
            }}
            className="field cursor-pointer"
          >
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.id})
              </option>
            ))}
          </select>
        </FieldRow>
        <FieldRow label="Venue">
          <select
            value={draft.venue_id}
            onChange={(e) => {
              const id = e.target.value;
              const v = venueById(id);
              const s = { ...draft, venue_id: id };
              if (v) {
                s.gate_distribution = {
                  ...Object.fromEntries(v.nodes.filter((n) => n.type === 'ENTRY').map((n, _i, arr) => [n.id, 1 / arr.length])),
                };
                s.destination_distribution = {
                  ...Object.fromEntries(
                    v.nodes.filter((n) => n.type === 'ZONE' || n.type === 'CONCESSION').map((n, _i, arr) => [n.id, 1 / arr.length]),
                  ),
                };
                s.exit_distribution = {
                  ...Object.fromEntries(
                    v.nodes.filter((n) => n.type === 'EXIT' || n.type === 'EMERGENCY_EXIT').map((n, _i, arr) => [n.id, 1 / arr.length]),
                  ),
                };
              }
              setDraft(s);
            }}
            className="field cursor-pointer"
          >
            {venues.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} ({v.id})
              </option>
            ))}
          </select>
        </FieldRow>
        <div className="ml-auto flex items-center gap-3">
          {notice && (
            <span className={`text-[10px] uppercase tracking-[0.12em] font-bold ${noticeTone === 'ok' ? 'text-od-ok' : 'text-od-danger'}`}>
              {notice}
            </span>
          )}
          <button onClick={save} disabled={saving} className="btn btn-solid">
            <Save className="h-3.5 w-3.5" /> {saving ? 'Saving…' : 'Save scenario'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 items-start lg:grid-cols-2">
        <div className="space-y-5">
          <div className="blk">
            <div className="blk-hd">
              <span className="sec-label">Crowd & demand</span>
            </div>
            <div className="space-y-2.5 px-4 py-4">
              <FieldRow label="Name">
                <input
                  value={draft.name}
                  onChange={(e) => set({ name: e.target.value })}
                  className="field flex-1 text-[11px] font-bold uppercase tracking-widest"
                />
              </FieldRow>
              <FieldRow label="Crowd size">
                <input
                  type="number"
                  min={1}
                  step={100}
                  value={draft.crowd_size}
                  onChange={(e) => set({ crowd_size: Math.max(1, Number(e.target.value)) })}
                  className="field flex-1 text-[11px] font-bold mono-tabular"
                />
              </FieldRow>
              <FieldRow label="Arrival (p/min)">
                <input
                  type="number"
                  min={1}
                  value={draft.arrival_rate_per_minute}
                  onChange={(e) => set({ arrival_rate_per_minute: Math.max(1, Number(e.target.value)) })}
                  className="field flex-1 text-[11px] font-bold mono-tabular"
                />
              </FieldRow>
              <FieldRow label="Exit surge (p/min)">
                <input
                  type="number"
                  min={0}
                  value={draft.exit_rate_per_minute}
                  onChange={(e) => set({ exit_rate_per_minute: Math.max(0, Number(e.target.value)) })}
                  className="field flex-1 text-[11px] font-bold mono-tabular"
                />
              </FieldRow>
              <FieldRow label="Departure spread">
                <input
                  type="number"
                  min={0.5}
                  step={0.5}
                  value={draft.surge_departure_spread_min}
                  onChange={(e) => set({ surge_departure_spread_min: Math.max(0.5, Number(e.target.value)) })}
                  className="field flex-1 text-[11px] font-bold mono-tabular"
                />
              </FieldRow>
            </div>
          </div>

          <DistEditor
            title="Entry gate distribution"
            value={draft.gate_distribution}
            options={gates.map((g) => ({ id: g.id, label: g.id }))}
            onChange={(v) => set({ gate_distribution: v })}
          />
        </div>

        <div className="space-y-5">
          <DistEditor
            title="Destination distribution"
            value={draft.destination_distribution}
            options={destinations.map((n) => ({ id: n.id, label: n.id }))}
            onChange={(v) => set({ destination_distribution: v })}
          />
          <DistEditor
            title="Exit distribution"
            value={draft.exit_distribution}
            options={exits.map((n) => ({ id: n.id, label: n.id }))}
            onChange={(v) => set({ exit_distribution: v })}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-2">
        <PhaseEditor phases={draft.event_phases} onChange={(p) => set({ event_phases: p })} />
        <div className="flex flex-col justify-between gap-5">
          <div className="blk border-l-2 border-l-od-warn px-4 py-3 text-[10px] uppercase tracking-[0.14em] leading-relaxed text-od-muted">
            Doors open → ENTRY ramp · kick-off → PEAK · half-time → INTERVAL · full-time → EXIT_SURGE
            where seated crowds depart in waves. Distributions must each sum to 1.0 or the backend
            rejects the save.
          </div>
          <button
            onClick={runSimulation}
            disabled={busy || !runnable}
            className="btn btn-solid w-full !py-2.5"
          >
            <Play className="h-3.5 w-3.5" /> {busy ? 'Starting…' : 'Run this scenario'}
          </button>
        </div>
      </div>
    </div>
  );
}
