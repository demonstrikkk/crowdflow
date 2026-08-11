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
    <div className="border border-outline-variant">
      <div className="flex items-center justify-between px-md py-sm bg-surface-container-low grid-line-bottom">
        <span className="text-[10px] font-bold uppercase tracking-[0.2em]">{title}</span>
        <span className={`text-[10px] font-bold mono-tabular ${ok ? 'text-primary' : 'text-error'}`}>
          Σ {total.toFixed(3)}
        </span>
      </div>
      <div className="px-md py-md space-y-sm">
        {options.map((o) => (
          <label key={o.id} className="flex items-center gap-sm text-[10px] uppercase tracking-[0.14em] text-secondary">
            <span className="w-24 truncate">{o.label}</span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={value[o.id] ?? 0}
              onChange={(e) => set(o.id, Math.max(0, Number(e.target.value)))}
              className="flex-1 bg-background border border-primary px-sm py-xs text-[11px] font-bold mono-tabular"
            />
          </label>
        ))}
        <button
          onClick={() => {
            const keys = Object.keys(value);
            const k = keys.length || options.length;
            const share = 1 / (k || 1);
            onChange(Object.fromEntries(options.map((o) => [o.id, share])));
          }}
          className="text-[9px] uppercase tracking-[0.18em] text-secondary underline underline-offset-4 cursor-pointer hover:text-primary"
        >
          Equalize
        </button>
      </div>
    </div>
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
    <div className="border border-outline-variant">
      <div className="flex items-center justify-between px-md py-sm bg-surface-container-low grid-line-bottom">
        <span className="text-[10px] font-bold uppercase tracking-[0.2em]">Event phases</span>
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
            className="btn-outline !py-xs"
          >
            <Plus className="w-3 h-3" /> Add phase
          </button>
        )}
      </div>
      <ul className="divide-y divide-outline-variant">
        {phases.map((p, i) => (
          <li key={i} className="px-md py-sm space-y-sm">
            <div className="flex items-center gap-sm">
              <select
                value={p.name}
                onChange={(e) => set(i, { name: e.target.value as EventPhaseName })}
                className="bg-background border border-primary px-sm py-xs text-[10px] font-bold uppercase tracking-widest cursor-pointer"
              >
                {PHASE_NAMES.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
              <span className="text-[9px] uppercase tracking-[0.16em] text-secondary mono-tabular">
                {p.start_minute}–{p.end_minute} min
              </span>
              <button
                onClick={() => onChange(phases.filter((_, j) => j !== i))}
                aria-label={`Remove phase ${i + 1}`}
                className="ml-auto p-xs text-error cursor-pointer hover:bg-error hover:text-background transition-none"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
            <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.14em] text-secondary">
              Start minute
              <input
                type="number"
                min={0}
                value={p.start_minute}
                onChange={(e) => set(i, { start_minute: Math.max(0, Number(e.target.value)) })}
                className="flex-1 bg-background border border-primary px-sm py-xs text-[11px] font-bold mono-tabular"
              />
            </label>
            <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.14em] text-secondary">
              End minute
              <input
                type="number"
                min={0}
                value={p.end_minute}
                onChange={(e) => set(i, { end_minute: Math.max(1, Number(e.target.value)) })}
                className="flex-1 bg-background border border-primary px-sm py-xs text-[11px] font-bold mono-tabular"
              />
            </label>
            <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.14em] text-secondary">
              Arrival multiplier
              <input
                type="number"
                min={0}
                step={0.1}
                value={p.arrival_rate_multiplier}
                onChange={(e) => set(i, { arrival_rate_multiplier: Math.max(0, Number(e.target.value)) })}
                className="flex-1 bg-background border border-primary px-sm py-xs text-[11px] font-bold mono-tabular"
              />
            </label>
            {p.name === 'EXIT_SURGE' && (
              <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.14em] text-secondary">
                Spawn mode
                <select
                  value={p.spawn ?? ''}
                  onChange={(e) =>
                    set(i, { spawn: e.target.value === '' ? null : e.target.value })
                  }
                  className="flex-1 bg-background border border-primary px-sm py-xs text-[10px] font-bold uppercase tracking-widest cursor-pointer"
                >
                  <option value="">from arrivals</option>
                  <option value="EXIT_SURGE">seated crowd leaves</option>
                  <option value="EVACUATION">evacuation</option>
                </select>
              </label>
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
      await refreshCatalog();
      await selectScenario(saved.id);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  }, [draft, scenarios, selectScenario, refreshCatalog]);

  if (!draft) {
    return (
      <div className="border border-outline-variant px-md py-xl text-[11px] uppercase tracking-[0.16em] text-secondary">
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
    <div className="space-y-lg">
      <div className="flex flex-wrap items-center gap-md">
        <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.2em] text-secondary">
          Load scenario
          <select
            value={source}
            onChange={(e) => {
              const s = scenarios.find((x) => x.id === e.target.value) ?? draft;
              if (s) {
                setDraft({ ...s });
                setSource(s.id);
              }
            }}
            className="bg-background border border-primary px-md py-sm text-[11px] font-bold uppercase tracking-widest cursor-pointer"
          >
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.id})
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.2em] text-secondary">
          Venue
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
            className="bg-background border border-primary px-md py-sm text-[11px] font-bold uppercase tracking-widest cursor-pointer"
          >
            {venues.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} ({v.id})
              </option>
            ))}
          </select>
        </label>
        <div className="ml-auto flex items-center gap-md">
          {notice && <span className="text-[10px] uppercase tracking-[0.14em] font-bold text-error">{notice}</span>}
          <button onClick={save} disabled={saving} className="btn-primary">
            <Save className="w-3.5 h-3.5" /> {saving ? 'Saving…' : 'Save scenario'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-lg items-start">
        <div className="space-y-lg">
          <div className="border border-outline-variant">
            <div className="px-md py-sm bg-surface-container-low grid-line-bottom text-[10px] font-bold uppercase tracking-[0.2em]">
              Crowd & demand
            </div>
            <div className="px-md py-md space-y-md">
              <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.16em] text-secondary">
                Name
                <input
                  value={draft.name}
                  onChange={(e) => set({ name: e.target.value })}
                  className="flex-1 bg-background border border-primary px-sm py-xs text-[11px] font-bold uppercase tracking-widest"
                />
              </label>
              <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.16em] text-secondary">
                Crowd size
                <input
                  type="number"
                  min={1}
                  step={100}
                  value={draft.crowd_size}
                  onChange={(e) => set({ crowd_size: Math.max(1, Number(e.target.value)) })}
                  className="flex-1 bg-background border border-primary px-sm py-xs text-[11px] font-bold mono-tabular"
                />
              </label>
              <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.16em] text-secondary">
                Arrival rate (p/min)
                <input
                  type="number"
                  min={1}
                  value={draft.arrival_rate_per_minute}
                  onChange={(e) => set({ arrival_rate_per_minute: Math.max(1, Number(e.target.value)) })}
                  className="flex-1 bg-background border border-primary px-sm py-xs text-[11px] font-bold mono-tabular"
                />
              </label>
              <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.16em] text-secondary">
                Exit-surge rate (p/min)
                <input
                  type="number"
                  min={0}
                  value={draft.exit_rate_per_minute}
                  onChange={(e) => set({ exit_rate_per_minute: Math.max(0, Number(e.target.value)) })}
                  className="flex-1 bg-background border border-primary px-sm py-xs text-[11px] font-bold mono-tabular"
                />
              </label>
              <label className="flex items-center gap-sm text-[10px] uppercase tracking-[0.16em] text-secondary">
                Departure spread (min)
                <input
                  type="number"
                  min={0.5}
                  step={0.5}
                  value={draft.surge_departure_spread_min}
                  onChange={(e) => set({ surge_departure_spread_min: Math.max(0.5, Number(e.target.value)) })}
                  className="flex-1 bg-background border border-primary px-sm py-xs text-[11px] font-bold mono-tabular"
                />
              </label>
            </div>
          </div>

          <DistEditor
            title="Entry gate distribution"
            value={draft.gate_distribution}
            options={gates.map((g) => ({ id: g.id, label: g.id }))}
            onChange={(v) => set({ gate_distribution: v })}
          />
        </div>

        <div className="space-y-lg">
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-lg items-start">
        <PhaseEditor phases={draft.event_phases} onChange={(p) => set({ event_phases: p })} />
        <div className="flex flex-col justify-between gap-lg">
          <div className="border border-outline-variant px-md py-md text-[10px] uppercase tracking-[0.16em] leading-relaxed text-secondary">
            iOS-style defaults per cue: doors open → ENTRY ramp; kick-off → PEAK; half-time →
            INTERVAL; full-time → EXIT_SURGE where seated crowds depart in waves. Distributions must
            each sum to 1.0 or the backend rejects the save.
          </div>
          <button
            onClick={runSimulation}
            disabled={busy || !runnable}
            className="btn-primary w-full"
          >
            <Play className="w-3.5 h-3.5" /> {busy ? 'Starting…' : 'Run this scenario'}
          </button>
        </div>
      </div>
    </div>
  );
}