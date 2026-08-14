import { Activity, Bot, Check, FlaskConical, Loader2, MapPin, Sparkles, Zap } from 'lucide-react';
import { useSimulation } from '../../store/SimulationContext';
import type { GeoAnchor } from '../../lib/geoProjection';
import type { Intervention } from '../../lib/types';
import type { WorldTool } from '../../lib/nav';
import { impactRows, interventionTitle } from '../../lib/interventions';

interface RightRailProps {
  anchor: GeoAnchor;
  onReAnchor: () => void;
  onRunWhatIf: (iv?: Intervention) => void;
  /** active tool drives which section gets the highlight ring */
  activeSection: WorldTool;
}

export default function RightRail({ anchor, onReAnchor, onRunWhatIf, activeSection }: RightRailProps) {
  const s = useSimulation();
  const candidates = s.optimization?.candidates ?? [];
  const hasMeaningful = (candidates[0]?.score ?? 0) > 0.001;

  return (
    <aside className="flex w-[300px] shrink-0 flex-col overflow-y-auto border-l border-od-line bg-od-panel/60 p-2 scrollbar-thin">
      {/* ── header ───────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-1 pb-1.5">
        <span className="sec-label">
          <em>AI</em>AI analyst & optimization
        </span>
        <span className="status-dot is-ok" title="Analysis engine ready" />
      </div>

      {/* ── STATUS ───────────────────────────────────────────────────── */}
      <section className="cmd-panel">
        <div className="cmd-panel-head">
          <span className="sec-label">Status</span>
        </div>
        <div className="flex items-center gap-2 p-2.5">
          <span className={`status-dot ${s.aiConfigured === false ? 'is-danger' : 'is-ok'}`} />
          <span className="mono-tabular text-[10px] uppercase tracking-[0.12em] text-od-ink">
            AI ready: {s.aiConfigured === false ? 'OFFLINE' : (s.aiProvider ?? 'unknown')}
          </span>
          {s.aiConfigured === false && (
            <span className="text-[9px] text-od-muted">set AI_API_KEY to enable</span>
          )}
        </div>
      </section>

      {/* ── ANALYSIS ─────────────────────────────────────────────────── */}
      <section className={`cmd-panel ${activeSection === 'ai' ? 'ring-1 ring-od-ok/40' : ''}`}>
        <div className="cmd-panel-head">
          <span className="sec-label">Analysis</span>
          <div className="flex items-center gap-1.5">
            <button
              className="btn btn-ghost !px-2 !py-0.5"
              onClick={() => void s.explainCurrent()}
              disabled={!s.sim || s.aiBusy}
              title="Ask the AI why this is happening"
            >
              <Bot className="h-3 w-3" /> WHY
            </button>
            <button
              className="btn btn-ghost !px-2 !py-0.5"
              onClick={() => void s.generateAiIdeas()}
              disabled={!s.scenario || s.aiBusy}
              title="Ask the AI for intervention ideas"
            >
              <Sparkles className="h-3 w-3" /> SUGGEST
            </button>
          </div>
        </div>

        <div className="space-y-3 p-2.5">
          {s.aiBusy && (
            <div className="flex items-center gap-2 text-[9px] uppercase tracking-[0.14em] text-od-muted">
              <Loader2 className="h-3 w-3 animate-spin" /> reasoning over simulation…
            </div>
          )}
          {s.aiError && <div className="text-[10px] leading-snug text-od-danger">{s.aiError}</div>}

          {/* WHY */}
          <div className="space-y-1">
            <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-od-warn">Why is this happening?</div>
            {s.aiExplanation?.summary ? (
              <p className="mono-tabular text-[10px] leading-snug text-od-soft">{s.aiExplanation.summary}</p>
            ) : (
              <p className="text-[10px] leading-snug text-od-muted">No diagnosis yet — select a bottleneck or press WHY.</p>
            )}
            {s.aiExplanation?.cause && (
              <p className="mono-tabular text-[10px] leading-snug text-od-muted">— {s.aiExplanation.cause}</p>
            )}
          </div>

          {/* WHAT SHOULD I DO */}
          <div className="space-y-1.5">
            <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-od-warn">What should I do?</div>
            {(s.aiExplanation?.try_actions ?? []).length > 0 && (
              <div className="space-y-1">
                {s.aiExplanation?.try_actions.map((a, i) => (
                  <button
                    key={i}
                    className="btn btn-ghost w-full justify-between !px-2 !py-1.5 text-left"
                    title="Run this recommendation as a real counterfactual simulation"
                    onClick={() => void onRunWhatIf({
                      id: typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}`,
                      type: a.type,
                      description: a.description,
                      parameters: a.parameters,
                    } as Intervention)}
                  >
                    <span className="mono-tabular text-[10px] text-od-ink">{a.description}</span>
                    <FlaskConical className="h-3 w-3 shrink-0 text-od-muted" />
                  </button>
                ))}
              </div>
            )}
            {s.aiIdeas.length > 0 && (
              <div className="space-y-1">
                {s.aiIdeas.map((idea, i) => (
                  <div key={i} className="border border-od-line bg-od-canvas/60 px-2 py-1.5">
                    <div className="text-[10px] font-bold uppercase tracking-[0.08em] text-od-ink">{idea.title}</div>
                    <div className="mt-0.5 text-[10px] leading-snug text-od-muted">{idea.description}</div>
                  </div>
                ))}
              </div>
            )}
            {!s.aiExplanation && s.aiIdeas.length === 0 && !s.aiBusy && (
              <p className="text-[10px] leading-snug text-od-muted">
                Press WHY to explain the current state, or SUGGEST for intervention ideas.
              </p>
            )}
          </div>
        </div>
      </section>

      {/* ── INTERVENTIONS (WHAT-IF) ──────────────────────────────────── */}
      <section className={`cmd-panel ${activeSection === 'whatif' || activeSection === 'optimize' ? 'ring-1 ring-od-warn/40' : ''}`}>
        <div className="cmd-panel-head">
          <span className="sec-label">Interventions · what-if</span>
          <button className="btn btn-ghost !px-2 !py-0.5" onClick={() => void s.optimize()} disabled={!s.simId || s.optimizing}>
            {s.optimizing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
            {s.optimization ? 'RERUN' : 'RUN'}
          </button>
        </div>

        <div className="space-y-2 p-2.5">
          {s.optimizing && (
            <div className="flex items-center gap-2 text-[9px] uppercase tracking-[0.14em] text-od-muted">
              <span className="status-dot is-scan" /> ranking candidate interventions…
            </div>
          )}

          {!s.optimizing && candidates.length === 0 && (
            <p className="text-[10px] leading-snug text-od-muted">
              Run the optimizer to simulate and rank candidate interventions against the live state.
            </p>
          )}

          {!s.optimizing && candidates.length > 0 && !hasMeaningful && (
            <div className="border border-od-line bg-od-canvas/60 p-2">
              <div className="flex items-center gap-2 text-[9px] uppercase tracking-[0.14em] text-od-ok">
                <Check className="h-3 w-3" /> Current state is already sound
              </div>
              <p className="mt-1 text-[10px] leading-snug text-od-muted">
                No intervention improves the simulated flow for the tested candidates.
              </p>
            </div>
          )}

          {candidates.map((cand, i) => {
            const isBest = i === 0 && hasMeaningful;
            const rows = impactRows(cand);
            return (
              <div
                key={cand.intervention.id}
                className={`border bg-od-canvas/60 p-2 ${isBest ? 'border-od-ok/60 shadow-[0_0_16px_-6px_rgba(16,185,129,0.5)]' : 'border-od-line'}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className={`text-[10px] font-bold uppercase tracking-[0.06em] ${isBest ? 'text-od-ok' : 'text-od-ink'}`}>
                    {interventionTitle(cand.intervention)}
                  </span>
                  <span
                    className={`mono-tabular text-[10px] font-bold ${isBest ? 'text-od-ok' : 'text-od-warn'}`}
                    title="Candidate score (0.0 – 1.0)"
                  >
                    SCORE {cand.score.toFixed(3)}
                  </span>
                </div>
                {rows.length > 0 && (
                  <div className="mt-1.5 space-y-0.5">
                    {rows.map((r) => (
                      <div key={r.label} className="flex items-center justify-between text-[9px] mono-tabular">
                        <span className="text-od-muted">{r.label}</span>
                        <span className={`font-bold ${r.good ? 'text-od-ok' : 'text-od-danger'}`}>{r.value}</span>
                      </div>
                    ))}
                  </div>
                )}
                <div className="mt-2 flex gap-1.5">
                  <button className="btn btn-ghost flex-1 !px-2 !py-1 text-[9px]" onClick={() => void onRunWhatIf(cand.intervention)}>
                    <FlaskConical className="h-3 w-3" /> SIMULATE
                  </button>
                  <button className="btn btn-solid flex-1 !px-2 !py-1 text-[9px]" onClick={() => void s.applyIntervention(cand.intervention)}>
                    <Activity className="h-3 w-3" /> APPLY
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── GEO ANCHOR ───────────────────────────────────────────────── */}
      <section className="cmd-panel">
        <div className="cmd-panel-head">
          <span className="sec-label">Geo anchor</span>
          <MapPin className="h-3 w-3 text-od-ok" />
        </div>
        <div className="space-y-2 p-2.5">
          <div className="flex items-center justify-between">
            <span className="text-[9px] uppercase tracking-[0.14em] text-od-muted">Latitude</span>
            <span className="mono-tabular text-[10px] font-bold text-od-ink">{anchor.lat.toFixed(4)}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[9px] uppercase tracking-[0.14em] text-od-muted">Longitude</span>
            <span className="mono-tabular text-[10px] font-bold text-od-ink">{anchor.lng.toFixed(4)}</span>
          </div>
          <div className="flex items-start justify-between gap-2 border-t border-od-line pt-2">
            <span className="text-[9px] uppercase tracking-[0.14em] text-od-muted">Location</span>
            <span className="text-right text-[10px] leading-snug text-od-ink">{anchor.name}</span>
          </div>
          <button className="btn btn-ghost w-full !py-1.5 text-[9px]" onClick={onReAnchor}>
            <MapPin className="h-3 w-3" /> RE-ANCHOR VENUE ON MAP
          </button>
          <div className="flex items-center justify-between border-t border-od-line pt-2 text-[9px] uppercase tracking-[0.14em] text-od-muted">
            <span>Bundle ID</span>
            <span className="mono-tabular text-od-ink">{s.venue?.id ?? '—'}</span>
          </div>
        </div>
      </section>
    </aside>
  );
}