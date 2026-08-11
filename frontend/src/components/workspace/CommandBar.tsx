import { useRef, useState } from 'react';
import { BrainCircuit, Loader2, Sparkles, Wand2, X } from 'lucide-react';
import { useSimulation } from '../../store/SimulationContext';
import { api } from '../../lib/api';
import type { AiInterpretResponse, ScenarioDelta } from '../../lib/types';

function deltaFacts(delta: ScenarioDelta): string[] {
  const facts: string[] = [];
  if (delta.crowd_size != null) facts.push(`${delta.crowd_size.toLocaleString()} crowd`);
  if (delta.close_gates?.length) facts.push(`close ${delta.close_gates.length} gate(s)`);
  if (delta.open_gates?.length) facts.push(`open ${delta.open_gates.length} gate(s)`);
  if (delta.close_edges?.length) facts.push(`close ${delta.close_edges.length} corridor(s)`);
  if (delta.open_edges?.length) facts.push(`open ${delta.open_edges.length} corridor(s)`);
  if (delta.incident) {
    const i = delta.incident;
    facts.push(`${i.type} at ${i.location} (r${i.radius_m}m${i.spread_rate_m_min ? `, +${i.spread_rate_m_min}/min` : ''})`);
  }
  if (delta.weather) {
    const w = delta.weather;
    facts.push(`${w.condition}${w.unsafe_outdoor ? ' — outdoor closed' : ''}`);
  }
  if (delta.event_end_delta_minutes != null) {
    facts.push(`exit surge ${delta.event_end_delta_minutes < 0 ? 'earlier' : 'later'} by ${Math.abs(delta.event_end_delta_minutes)}m`);
  }
  if (facts.length === 0) facts.push('no operational change');
  return facts;
}

export default function CommandBar() {
  const s = useSimulation();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [preview, setPreview] = useState<AiInterpretResponse | null>(null);
  const [interpreting, setInterpreting] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const runQuery = async (q: string, delta?: ScenarioDelta) => {
    setOpen(true);
    const ok = await s.runAiSimulation(q, delta);
    if (ok) setQuery('');
  };

  const interpret = async () => {
    const q = query.trim();
    if (!q || !s.scenario) return;
    setInterpreting(true);
    setPreview(null);
    try {
      setPreview(await api.aiInterpret(q, s.scenario.id));
    } catch {
      setPreview(null);
      setOpen(true);
      void s.runAiSimulation(q);
    } finally {
      setInterpreting(false);
    }
  };

  return (
    <div className="relative">
      <button
        className="btn btn-ghost gap-1.5"
        onClick={() => {
          setOpen((o) => !o);
          if (!open) setTimeout(() => inputRef.current?.focus(), 0);
        }}
        aria-expanded={open}
        aria-label="AI command bar"
        title="Describe an event in plain language"
      >
        <BrainCircuit className="h-3.5 w-3.5" />
        <span className="hidden xl:inline">AI COMMAND</span>
      </button>

      {open && (
        <div className="absolute right-0 top-[calc(100%+6px)] z-30 w-[min(440px,calc(100vw-2rem))] border border-od-line bg-od-panel shadow-xl">
          <div className="flex items-center justify-between border-b border-od-line px-3 py-2">
            <span className="text-[9px] uppercase tracking-[0.2em] text-od-muted flex items-center gap-1.5">
              <Wand2 className="h-3 w-3" />
              Natural-language event builder
              {s.aiProvider && <span className="text-od-ok">· {s.aiProvider}</span>}
            </span>
            <button className="cursor-pointer text-od-muted hover:text-od-ink" onClick={() => setOpen(false)} aria-label="Close command bar">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="p-3 space-y-2.5">
            <div className="flex gap-1.5">
              <input
                ref={inputRef}
                className="field flex-1"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void interpret();
                }}
                placeholder='e.g. "close gate C and make it rain"'
                disabled={!s.scenario}
              />
              <button
                className="btn btn-solid"
                onClick={() => void interpret()}
                disabled={!query.trim() || !s.scenario || interpreting}
                aria-label="Interpret query"
              >
                {interpreting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              </button>
            </div>

            {preview && (
              <div className="border border-od-line bg-od-canvas px-2.5 py-2 space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[9px] uppercase tracking-[0.18em] text-od-muted">
                    Interpreted · confidence {Math.round(preview.confidence * 100)}%
                  </span>
                  {preview.model && <span className="text-[9px] uppercase tracking-[0.14em] text-od-muted">{preview.model}</span>}
                </div>
                <div className="flex flex-wrap gap-1">
                  {deltaFacts(preview.delta).map((f) => (
                    <span key={f} className="chip is-active text-[9px]">{f}</span>
                  ))}
                </div>
                {preview.reasoning && <p className="text-[10px] leading-snug text-od-muted">{preview.reasoning}</p>}
                <div className="flex gap-1.5 pt-1">
                  <button
                    className="btn btn-solid flex-1"
                    onClick={() => void runQuery(query.trim(), preview.delta)}
                  >
                    RUN THIS VARIANT
                  </button>
                  <button className="btn btn-ghost" onClick={() => void runQuery(query.trim())} title="Re-interpret directly on the backend">
                    RUN RAW
                  </button>
                </div>
              </div>
            )}

            {s.aiIdeas.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[9px] uppercase tracking-[0.2em] text-od-muted">Suggested variants</div>
                {s.aiIdeas.map((idea, i) => (
                  <button
                    key={idea.id ?? i}
                    className="w-full border border-od-line hover:border-od-ink text-left px-2.5 py-1.5 cursor-pointer"
                    onClick={() => void runQuery(idea.title, idea.delta)}
                  >
                    <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-od-ink">{idea.title}</div>
                    <div className="text-[10px] text-od-muted mt-0.5 leading-snug">{idea.description}</div>
                  </button>
                ))}
              </div>
            )}

            {s.aiExplanation && (
              <div className="border border-od-warn bg-od-warn-soft px-2.5 py-2 space-y-1.5">
                <div className="text-[9px] uppercase tracking-[0.18em] text-od-warn">Grounded explanation</div>
                <p className="text-[10px] text-od-ink leading-snug">{s.aiExplanation.summary}</p>
                <p className="text-[10px] text-od-muted leading-snug">Cause: {s.aiExplanation.cause}</p>
                {s.aiExplanation.try_actions.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {s.aiExplanation.try_actions.map((a) => (
                      <span key={a.description} className="chip">{a.description}</span>
                    ))}
                  </div>
                )}
              </div>
            )}

            {s.aiError && (
              <div className="border border-od-danger bg-od-danger-soft px-2.5 py-1.5 text-[10px] text-od-danger uppercase tracking-[0.1em]">
                {s.aiError}
              </div>
            )}

            <div className="flex gap-1.5">
              <button
                className="btn btn-ghost flex-1"
                onClick={() => void s.generateAiIdeas()}
                disabled={!s.scenario || s.aiBusy}
              >
                {s.aiBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                SUGGEST VARIATIONS
              </button>
              <button
                className="btn btn-ghost flex-1"
                onClick={() => void s.explainCurrent()}
                disabled={!s.simId || s.aiBusy}
              >
                WHY IS IT CONGESTED?
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
