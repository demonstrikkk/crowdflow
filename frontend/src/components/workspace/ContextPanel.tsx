import { useMemo, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import type { ElementState, Intervention, SimulationState, VenueModel } from '../../lib/types';
import { riskState } from '../../lib/format';
import type { Mode, Selection } from '../../lib/selection';
import type { DraftState, RedirectDraft } from './InstrumentCanvas';

export interface PanelProps {
  mode: Mode;
  sim: SimulationState | null;
  venue: VenueModel | null;
  selected: Selection | null;
  onSelect: (sel: Selection | null) => void;
  guidedCta: (() => void) | null;
  drafts: DraftState | null;
  onToggleClose: (edgeKey: string) => void;
  onImplementClose: (edgeKey: string) => void;
  onSetRedirect: (r: RedirectDraft | null) => void;
  onImplementRedirect: (r: RedirectDraft) => void;
  onEmergency: (active: boolean) => void;
  onIntervention: (i: Intervention) => void;
  cfSim: SimulationState | null;
  cfError: string | null;
  onDiscardCf: () => void;
  onApplyCf: () => void;
  runCounterfactual: (intervention: Intervention) => Promise<string | null>;
  onClosePanel?: () => void;
}

function fmt(n: number | undefined | null, digits = 0) {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function Section({
  n,
  title,
  right,
  children,
}: {
  n: string;
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="flex items-center gap-2 pb-2">
        <span className="font-mono text-[9px] font-bold text-od-danger">{n}</span>
        <span className="sec-label">{title}</span>
        <span className="h-px flex-1 bg-od-line" />
        {right}
      </div>
      {children}
    </section>
  );
}

function RiskBadge({ risk }: { risk: string }) {
  const s = riskState(risk as never);
  return (
    <span className={`chip ${s === 'danger' ? 'is-danger' : s === 'warn' ? 'is-warn' : 'is-ok'}`}>
      <span className={`status-dot ${s === 'danger' ? 'is-danger' : s === 'warn' ? 'is-warn' : 'is-ok'}`} />
      {risk}
    </span>
  );
}

function MetricGrid({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <div className="grid grid-cols-3 gap-x-3 gap-y-2.5 border-t border-od-line pt-2.5">
      {items.map(([label, value]) => (
        <div key={label}>
          <div className="meta">{label}</div>
          <div className="num mt-0.5 text-od-ink">{value}</div>
        </div>
      ))}
    </div>
  );
}

function ObjectDetail({
  sim,
  venue,
  selected,
}: {
  sim: SimulationState | null;
  venue: VenueModel | null;
  selected: Selection;
}) {
  const node = selected.kind === 'node' ? venue?.nodes.find((n) => n.id === selected.id) : null;
  const edge =
    selected.kind === 'edge' ? venue?.edges.find((e) => `${e.source}→${e.destination}` === selected.id) : null;
  const st: ElementState | undefined =
    sim?.nodes[selected.id] ?? (selected.kind === 'edge' ? sim?.edges[selected.id] : undefined);

  const title =
    selected.kind === 'node'
      ? (node?.id.replace(/_/g, ' ') ?? '?')
      : `${edge?.source.replace(/_/g, ' ')} → ${edge?.destination.replace(/_/g, ' ')}`;
  const type = selected.kind === 'node' ? (node?.type ?? 'NODE') : 'CORRIDOR';

  const metrics: [string, React.ReactNode][] = [];
  if (st) {
    metrics.push(
      ['People', fmt(st.people)],
      ['Queue', fmt(st.queue)],
      ['Density', fmt(st.density, 2)],
      ['Flow/min', fmt(st.flow_per_min)],
      ['Utilisation', `${fmt(st.utilisation * 100, 0)}%`],
      ['Capacity', fmt(st.capacity)],
    );
    if (st.time_to_critical_min != null) {
      metrics.push(['TTC', <span key="ttc" className="text-od-warn">{st.time_to_critical_min.toFixed(1)} min</span>]);
    }
  }

  return (
    <Section n="03" title="Selected">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="num truncate text-[13px] font-bold uppercase tracking-[0.04em] text-od-ink">{title}</div>
          <div className="meta mt-0.5">{type}</div>
        </div>
        {st && <RiskBadge risk={st.risk} />}
      </div>
      {metrics.length > 0 && <MetricGrid items={metrics} />}
      <div className="mt-2.5 border-t border-od-line pt-2.5 text-[10px] text-od-muted mono-tabular">
        {selected.kind === 'edge' && edge
          ? `${edge.length_m} m × ${edge.width_m} m · ${edge.is_open ? 'open' : 'closed'}`
          : node
            ? `${node.type}${node.capacity ? ` · capacity ${node.capacity}` : ''}`
            : '—'}
      </div>
    </Section>
  );
}

function SystemReadout({ sim, onSelect }: { sim: SimulationState | null; onSelect: (sel: Selection) => void }) {
  const m = sim?.metrics;
  const top = sim?.bottlenecks[0];
  return (
    <Section n="01" title="System" right={m && <RiskBadge risk={m.risk_level} />}>
      {m && (
        <MetricGrid
          items={[
            ['In venue', fmt(m.in_venue)],
            ['Flow/min', fmt(m.flow_per_min)],
            ['Density', fmt(m.global_density, 2)],
            ['Queue', fmt(m.queue_total)],
            ['Bottlenecks', fmt(m.bottleneck_count)],
            ['Avg travel', `${fmt(m.avg_travel_time_min, 1)}m`],
          ]}
        />
      )}

      {top && (
        <button
          className="mt-3 w-full border border-od-line border-l-2 border-l-od-warn text-left px-2.5 py-2 cursor-pointer transition-colors hover:border-od-ink"
          onClick={() => onSelect({ kind: 'edge', id: top.location })}
        >
          <div className="flex items-center justify-between">
            <span className="meta">Top bottleneck</span>
            <RiskBadge risk={top.current_risk} />
          </div>
          <div className="num mt-1 text-od-ink">{top.location}</div>
          <div className="text-[10px] leading-snug text-od-muted mt-1">{top.explanation}</div>
        </button>
      )}

      {sim?.recommended_action && (
        <div className="mt-3 border border-od-warn bg-od-warn-soft px-2.5 py-2">
          <div className="meta text-od-warn">Recommended action</div>
          <div className="text-[11px] text-od-ink mt-0.5 leading-snug">{sim.recommended_action}</div>
        </div>
      )}
    </Section>
  );
}

function BottleneckRegister({
  sim,
  onSelect,
}: {
  sim: SimulationState | null;
  onSelect: (sel: Selection) => void;
}) {
  const sorted = useMemo(() => {
    const list = [...(sim?.bottlenecks ?? [])];
    list.sort((a, b) => b.current_risk.localeCompare(a.current_risk));
    return list;
  }, [sim?.bottlenecks]);
  return (
    <Section n="02" title={`Bottlenecks · ${sorted.length}`}>
      {sorted.length === 0 && <p className="text-[11px] text-od-muted">No congestion detected at this instant.</p>}
      <div className="space-y-1.5">
        {sorted.map((b) => {
          const s = riskState(b.current_risk as never);
          const sel: Selection = { kind: b.kind, id: b.location };
          const accent = s === 'danger' ? 'border-l-od-danger' : s === 'warn' ? 'border-l-od-warn' : 'border-l-od-ok';
          return (
            <button
              key={b.id}
              className={`w-full border border-od-line border-l-2 ${accent} text-left px-2.5 py-2 cursor-pointer transition-colors hover:border-od-ink`}
              onClick={() => onSelect(sel)}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="meta">{b.kind}</span>
                <span className={`status-dot ${s === 'danger' ? 'is-danger' : s === 'warn' ? 'is-warn' : 'is-ok'}`} />
              </div>
              <div className="num mt-0.5 truncate text-od-ink">{b.location}</div>
              <div className="flex justify-between text-[10px] text-od-muted mt-1 mono-tabular">
                <span>util {fmt(b.capacity_utilisation * 100, 0)}%</span>
                <span>queue {fmt(b.queue)}</span>
                <span>density {fmt(b.current_density, 2)}</span>
              </div>
            </button>
          );
        })}
      </div>
    </Section>
  );
}

function InterveneComposer({
  sim,
  venue,
  selected,
  drafts,
  onToggleClose,
  onImplementClose,
  onSetRedirect,
  onImplementRedirect,
  onEmergency,
}: {
  sim: SimulationState | null;
  venue: VenueModel | null;
  selected: Selection | null;
  drafts: DraftState | null;
  onToggleClose: (edgeKey: string) => void;
  onImplementClose: (edgeKey: string) => void;
  onSetRedirect: (r: RedirectDraft | null) => void;
  onImplementRedirect: (r: RedirectDraft) => void;
  onEmergency: (active: boolean) => void;
}) {
  const gates = venue?.nodes.filter((n) => n.type === 'ENTRY') ?? [];
  const closed = new Set(drafts?.closedEdgeIds ?? []);
  const rd = drafts?.redirect ?? null;

  return (
    <div className="space-y-5">
      <Section n="01" title="Intervention">
        <div className="border-t border-od-line pt-2.5">
          <div className="meta mb-1.5">Corridors</div>
          {closed.size === 0 && <p className="text-[11px] text-od-muted mb-1.5">Select a corridor on the canvas, then close it here.</p>}
          {[...closed].map((key) => (
            <div key={key} className="mb-1.5 flex items-center gap-2 border border-od-danger bg-od-danger-soft px-2 py-1.5">
              <span className="flex-1 truncate text-[10px] uppercase tracking-[0.1em] text-od-ink">{key}</span>
              <button className="btn btn-danger" onClick={() => onImplementClose(key)}>
                CLOSE
              </button>
            </div>
          ))}
        </div>

        {selected?.kind === 'edge' && (
          <button
            className="btn btn-danger w-full"
            onClick={() => {
              onToggleClose(selected.id);
              onImplementClose(selected.id);
            }}
          >
            CLOSE SELECTED CORRIDOR
          </button>
        )}

        <div className="mt-3 border-t border-od-line pt-2.5">
          <div className="meta mb-1.5">Redirect a gate</div>
          <div className="flex flex-wrap gap-1">
            {gates.map((g) => (
              <button
                key={g.id}
                className={`chip ${rd?.from === g.id ? 'is-active' : ''}`}
                onClick={() => {
                  if (rd?.from === g.id) onSetRedirect(null);
                  else {
                    const target = venue?.nodes.find((n) => n.type === 'EXIT');
                    if (target) onSetRedirect({ from: g.id, to: target.id, pct: 20 });
                  }
                }}
              >
                {g.id.replace(/_/g, ' ')}
              </button>
            ))}
          </div>
          {rd && (
            <div className="mt-2 space-y-2 border border-od-warn bg-od-warn-soft px-2.5 py-2">
              <div className="num truncate text-od-ink">
                {rd.from.replace(/_/g, ' ')} → {rd.to.replace(/_/g, ' ')}
              </div>
              <label className="block">
                <span className="meta">Reroute share</span>
                <input
                  type="range"
                  min={5}
                  max={70}
                  step={5}
                  value={rd.pct}
                  onChange={(e) => onSetRedirect({ ...rd, pct: Number(e.target.value) })}
                  className="slider w-full mt-1"
                />
                <span className="num text-od-ink">{rd.pct}%</span>
              </label>
              <div className="flex gap-1.5">
                <button className="btn btn-solid flex-1" onClick={() => onImplementRedirect(rd)}>
                  IMPLEMENT
                </button>
                <button className="btn btn-ghost" onClick={() => onSetRedirect(null)}>
                  CLEAR
                </button>
              </div>
            </div>
          )}
        </div>
      </Section>

      <Section n="02" title="Emergency">
        <button
          className="btn btn-danger w-full"
          onClick={() => onEmergency(!(sim?.emergency_active ?? false))}
        >
          {sim?.emergency_active ? 'CANCEL EVACUATION' : 'DECLARE EVACUATION'}
        </button>
      </Section>

      {sim && sim.interventions_applied.length > 0 && (
        <Section n="03" title={`Applied · ${sim.interventions_applied.length}`}>
          {sim.interventions_applied.map((i) => (
            <div key={i.id} className="border-b border-od-line py-1 text-[10px] uppercase tracking-[0.1em] text-od-muted last:border-0">
              {i.description}
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}

function ConditionsComposer({
  sim,
  selected,
  onIntervention,
}: {
  sim: SimulationState | null;
  selected: Selection | null;
  onIntervention: (i: Intervention) => void;
}) {
  const [incidentType, setIncidentType] = useState<'FIRE' | 'SECURITY' | 'STRUCTURAL'>('FIRE');
  const [incidentRadius, setIncidentRadius] = useState(40);
  const [incidentSpread, setIncidentSpread] = useState(0);
  const [weather, setWeather] = useState<'CLEAR' | 'FOG' | 'HEAVY_RAIN' | 'HAIL' | 'HEAT'>('HEAVY_RAIN');
  const [unsafe, setUnsafe] = useState(false);

  const location = selected?.kind === 'node' ? selected.id : sim?.incident?.location ?? 'CONCOURSE_N';

  const startIncident = () => {
    onIntervention({
      id: `inc-${Date.now()}`,
      type: 'ADD_INCIDENT',
      description: `${incidentType} at ${location} (r${incidentRadius}m${incidentSpread ? `, +${incidentSpread}/min` : ''})`,
      parameters: {
        incident: {
          type: incidentType,
          location,
          radius_m: incidentRadius,
          spread_rate_m_min: incidentSpread,
          severity: incidentRadius >= 60 || incidentSpread > 0 ? 'SEVERE' : 'MODERATE',
          blocks_exits: [],
        },
      },
    });
  };

  const applyWeather = () => {
    const condition = weather;
    onIntervention({
      id: `wx-${Date.now()}`,
      type: 'SET_WEATHER',
      description: `${condition.replace(/_/g, ' ')}${unsafe ? ' — outdoor routes closed' : ''}`,
      parameters: {
        weather: {
          condition,
          capacity_multiplier: condition === 'CLEAR' ? 1 : condition === 'FOG' ? 0.75 : 0.55,
          speed_multiplier: condition === 'CLEAR' ? 1 : condition === 'FOG' ? 0.85 : 0.7,
          unsafe_outdoor: unsafe,
          applies_outdoor_only: true,
        },
      },
    });
  };

  const hasConditions = !!(sim?.incident || sim?.weather);

  return (
    <Section n="03" title="Conditions" right={hasConditions ? <span className="chip is-danger text-[8px]">active</span> : undefined}>
      <div className="border-t border-od-line pt-2.5 space-y-2">
        <div className="meta">Incident</div>
        <div className="flex gap-1">
          {(['FIRE', 'SECURITY', 'STRUCTURAL'] as const).map((t) => (
            <button
              key={t}
              className={`chip ${incidentType === t ? 'is-active' : ''}`}
              onClick={() => setIncidentType(t)}
            >
              {t}
            </button>
          ))}
        </div>
        <label className="block">
          <span className="meta">Location</span>
          <span className="num block text-od-ink">{location.replace(/_/g, ' ')}</span>
          {selected?.kind !== 'node' && <span className="text-[9px] text-od-muted">(select a node on the canvas to aim it)</span>}
        </label>
        <label className="block">
          <span className="meta">Radius {incidentRadius}m</span>
          <input type="range" min={15} max={120} step={5} value={incidentRadius} onChange={(e) => setIncidentRadius(Number(e.target.value))} className="slider w-full mt-1" />
        </label>
        <label className="block">
          <span className="meta">Spread {incidentSpread}m/min</span>
          <input type="range" min={0} max={2} step={0.1} value={incidentSpread} onChange={(e) => setIncidentSpread(Number(e.target.value))} className="slider w-full mt-1" />
        </label>
        <button className="btn btn-danger w-full" onClick={startIncident} disabled={!sim}>
          START {incidentType}
        </button>
      </div>

      <div className="mt-3 border-t border-od-line pt-2.5 space-y-2">
        <div className="meta">Weather</div>
        <div className="flex flex-wrap gap-1">
          {(['CLEAR', 'FOG', 'HEAVY_RAIN', 'HAIL', 'HEAT'] as const).map((w) => (
            <button
              key={w}
              className={`chip ${weather === w ? 'is-active' : ''}`}
              onClick={() => setWeather(w)}
            >
              {w.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-[10px] uppercase tracking-[0.12em] text-od-muted">
          <input type="checkbox" checked={unsafe} onChange={(e) => setUnsafe(e.target.checked)} />
          Close outdoor routes
        </label>
        <button className="btn btn-solid w-full" onClick={applyWeather} disabled={!sim}>
          APPLY WEATHER
        </button>
      </div>
    </Section>
  );
}

function CompareReadout({ sim, cfSim, cfError }: { sim: SimulationState | null; cfSim: SimulationState | null; cfError: string | null }) {
  const base = sim?.metrics;
  const alt = cfSim?.metrics;
  const rows: [string, string | number | null, string | number | null, (a: number, b: number) => boolean][] = [
    ['In venue', base?.in_venue ?? null, alt?.in_venue ?? null, (a, b) => a <= b],
    ['Avg travel', base?.avg_travel_time_min ?? null, alt?.avg_travel_time_min ?? null, (a, b) => a <= b],
    ['Max utilisation', base?.max_utilisation ?? null, alt?.max_utilisation ?? null, (a, b) => a <= b],
    ['Queue total', base?.queue_total ?? null, alt?.queue_total ?? null, (a, b) => a <= b],
    ['Bottlenecks', base?.bottleneck_count ?? null, alt?.bottleneck_count ?? null, (a, b) => a <= b],
  ];
  return (
    <Section n="01" title="Comparison">
      {cfError && <p className="text-[11px] text-od-danger">{cfError}</p>}
      {!cfSim && !cfError && (
        <p className="text-[11px] leading-relaxed text-od-muted">
          Draft an intervention in INTERVENE and run it as a counterfactual to see it here side by side.
        </p>
      )}
      {cfSim && (
        <div className="border-t border-od-line pt-2.5">
          <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-3 gap-y-1.5 text-[10px] uppercase tracking-[0.12em]">
            <span className="meta">Metric</span>
            <span className="meta text-right">Base</span>
            <span className="meta text-right">Alt</span>
            <span className="meta text-right">Δ</span>
            {rows.map(([label, a, b, better]) => {
              const an = typeof a === 'number' ? a : null;
              const bn = typeof b === 'number' ? b : null;
              const delta = an != null && bn != null ? bn - an : null;
              const good = delta != null && an != null && bn != null ? better(an, bn) : true;
              return (
                <div key={label} className="contents">
                  <span className="text-od-muted pt-0.5">{label}</span>
                  <span className="num text-right text-od-ink">{fmt(an, 1)}</span>
                  <span className="num text-right text-od-ink">{fmt(bn, 1)}</span>
                  <span className={`num text-right ${delta == null ? '' : good ? 'text-od-ok' : 'text-od-danger'}`}>
                    {delta == null ? '—' : `${delta >= 0 ? '+' : ''}${delta.toFixed(1)}`}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="mt-2 border-t border-od-line pt-2">
            <div className="meta mb-1">Clearance time</div>
            <div className="num text-od-ink">
              {fmt(base?.clearance_time_min, 1)}m <span className="text-od-muted">→</span> {fmt(alt?.clearance_time_min, 1)}m
            </div>
          </div>
        </div>
      )}
    </Section>
  );
}

export default function ContextPanel(props: PanelProps) {
  const { mode, sim, selected, onSelect, guidedCta } = props;
  return (
    <aside className="hidden w-80 shrink-0 flex-col border-l border-od-line bg-od-panel lg:flex">
      <div className="flex shrink-0 items-center justify-between border-b border-od-line px-3 py-2">
        <span className="sec-label">
          {mode === 'compare' ? 'Outcome' : mode === 'intervene' ? 'Intervention' : mode === 'investigate' ? 'Diagnostics' : 'System'}
        </span>
        {props.onClosePanel && (
          <button
            onClick={props.onClosePanel}
            className="cursor-pointer text-od-muted transition-colors hover:text-od-ink"
            aria-label="Collapse context panel"
            title="Collapse — keep the venue in focus"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-3 py-3">
        {mode === 'intervene' ? (
          <>
            <InterveneComposer {...props} />
            <ConditionsComposer sim={sim} selected={selected} onIntervention={props.onIntervention} />
          </>
        ) : mode === 'compare' ? (
          <CompareReadout sim={sim} cfSim={props.cfSim} cfError={props.cfError} />
        ) : mode === 'investigate' ? (
          <>
            <BottleneckRegister sim={sim} onSelect={onSelect} />
            {selected && <ObjectDetail sim={sim} venue={props.venue} selected={selected} />}
          </>
        ) : (
          <>
            {guidedCta && (
              <button
                className="w-full border border-od-warn border-l-2 border-l-od-warn bg-od-warn-soft text-left px-2.5 py-2.5 cursor-pointer transition-colors hover:bg-od-warn-soft"
                onClick={guidedCta}
              >
                <div className="meta text-od-warn">Action required</div>
                <div className="mt-0.5 text-[12px] font-bold uppercase tracking-[0.06em] text-od-ink">
                  Bottleneck forming — see what we can change
                </div>
              </button>
            )}
            <SystemReadout sim={sim} onSelect={onSelect} />
            {selected && <ObjectDetail sim={sim} venue={props.venue} selected={selected} />}
          </>
        )}
      </div>
      <div className="flex shrink-0 items-center justify-between border-t border-od-line px-3 py-2">
        <span className="sec-label">{mode} mode</span>
        {sim && (
          <span className="sec-label mono-tabular">t=<span className="text-od-ink">{sim.t_min.toFixed(1)}m</span></span>
        )}
      </div>
    </aside>
  );
}
