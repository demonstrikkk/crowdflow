import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';
import { useSimulation } from '../../store/SimulationContext';
import { api } from '../../lib/api';
import type { AiInterpretResponse, AiSuggestion, ScenarioDelta, SimulationState } from '../../lib/types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function deltaFacts(delta: ScenarioDelta): string[] {
  const facts: string[] = [];
  if (delta.crowd_size != null) facts.push(`crowd: ${delta.crowd_size.toLocaleString()}`);
  if (delta.close_gates?.length) facts.push(`close gate${delta.close_gates.length > 1 ? 's' : ''} ${delta.close_gates.join(', ')}`);
  if (delta.open_gates?.length) facts.push(`open gate${delta.open_gates.length > 1 ? 's' : ''} ${delta.open_gates.join(', ')}`);
  if (delta.close_edges?.length) facts.push(`close ${delta.close_edges.length} corridor(s)`);
  if (delta.open_edges?.length) facts.push(`open ${delta.open_edges.length} corridor(s)`);
  if (delta.incident) {
    facts.push(`${delta.incident.type} at ${delta.incident.location}`);
  }
  if (delta.weather) {
    facts.push(delta.weather.condition);
  }
  if (delta.event_end_delta_minutes != null) {
    const sign = delta.event_end_delta_minutes < 0 ? 'earlier' : 'later';
    facts.push(`exit surge ${Math.abs(delta.event_end_delta_minutes)}m ${sign}`);
  }
  if (facts.length === 0) facts.push('no operational change');
  return facts;
}

function suggestedPrompts(
  sim: SimulationState | null,
  aiIdeas: AiSuggestion[],
): string[] {
  const prompts: string[] = [];
  if (sim?.bottlenecks.length) {
    prompts.push(`Explain the bottleneck at ${sim.bottlenecks[0].location}`);
    prompts.push('What can I do about the congestion?');
  }
  if (sim?.status === 'RUNNING') {
    prompts.push('What happens if I close Gate A?');
    prompts.push('Show me the worst-case scenario');
  }
  for (const idea of aiIdeas.slice(0, 2)) prompts.push(idea.title);
  return prompts.slice(0, 4);
}

// ---------------------------------------------------------------------------
// Provider status dot
// ---------------------------------------------------------------------------

function ProviderDot({ configured }: { configured: boolean | null }) {
  const color =
    configured === true
      ? 'bg-green-500'
      : configured === false
        ? 'bg-red-500'
        : 'bg-yellow-400';
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}

// ---------------------------------------------------------------------------
// CommandBarBanner
// ---------------------------------------------------------------------------

export default function CommandBarBanner() {
  const s = useSimulation();
  const {
    sim,
    cfSim,
    cfSimId,
    aiConfigured,
    aiProvider,
    aiBusy,
    aiIdeas,
    aiExplanation,
    aiError,
    runAiSimulation,
  } = s;

  const [expanded, setExpanded] = useState(false);
  const [inputText, setInputText] = useState('');
  const [interpreting, setInterpreting] = useState(false);
  const [preview, setPreview] = useState<AiInterpretResponse | null>(null);

  // Ghost text shown in the collapsed bar when there are bottlenecks
  const ghostText =
    sim?.bottlenecks.length
      ? `Explain the bottleneck at ${sim.bottlenecks[0].location}`
      : null;

  // Suggested prompt chips
  const chips = suggestedPrompts(sim, aiIdeas);

  // ---------------------------------------------------------------------------
  // interpret: call aiInterpret, set preview; guard against duplicate calls
  // ---------------------------------------------------------------------------
  const interpret = async () => {
    if (interpreting) return;
    const q = inputText.trim();
    if (!q) return;
    setInterpreting(true);
    setPreview(null);
    try {
      if (s.scenario) {
        const result = await api.aiInterpret(q, s.scenario.id);
        setPreview(result);
      } else {
        // No scenario yet — fall back to direct simulation
        await runAiSimulation(q);
      }
    } catch {
      // On error, fall through — aiError from context will surface it
      await runAiSimulation(q);
    } finally {
      setInterpreting(false);
    }
  };

  // Run a variant from preview
  const runVariant = async (text: string, delta?: ScenarioDelta) => {
    const ok = await runAiSimulation(text, delta);
    if (ok) {
      setInputText('');
      setPreview(null);
      setExpanded(false);
    }
  };

  // Chip click: fill input and immediately interpret
  const onChipClick = (prompt: string) => {
    setInputText(prompt);
    void (async () => {
      if (interpreting) return;
      setInterpreting(true);
      setPreview(null);
      try {
        if (s.scenario) {
          const result = await api.aiInterpret(prompt, s.scenario.id);
          setPreview(result);
        } else {
          await runAiSimulation(prompt);
        }
      } catch {
        await runAiSimulation(prompt);
      } finally {
        setInterpreting(false);
      }
    })();
  };

  // "Did this improve?" button
  const didItHelp = async () => {
    if (!cfSimId) return;
    await api.aiExplain(cfSimId);
  };

  const inputDisabled = aiConfigured === false;
  const inputPlaceholder =
    inputDisabled
      ? 'AI not configured — check Settings'
      : '🧠 Ask CrowdFlow...';

  return (
    <div
      className="w-full border-b"
      style={{
        background: 'var(--od-panel)',
        borderColor: 'var(--od-line)',
      }}
    >
      {/* ------------------------------------------------------------------ */}
      {/* Collapsed bar                                                        */}
      {/* ------------------------------------------------------------------ */}
      <div
        className="flex h-8 cursor-pointer items-center justify-between px-3"
        onClick={() => setExpanded((v) => !v)}
        role="button"
        aria-expanded={expanded}
        aria-label="AI command bar"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') setExpanded((v) => !v);
        }}
      >
        {/* Left: prompt text / ghost text */}
        <span
          className="text-[10px] uppercase tracking-[0.18em] select-none"
          style={{ color: 'var(--od-muted)' }}
        >
          🧠{' '}
          {ghostText && !expanded ? (
            <span style={{ color: 'var(--od-muted)', opacity: 0.65 }}>{ghostText}</span>
          ) : (
            'Ask CrowdFlow...'
          )}
        </span>

        {/* Right: provider status */}
        <span className="flex items-center gap-1.5">
          <ProviderDot configured={aiConfigured} />
          {aiProvider && (
            <span
              className="text-[9px] uppercase tracking-[0.15em]"
              style={{ color: 'var(--od-muted)' }}
            >
              {aiProvider}
            </span>
          )}
        </span>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Expanded panel (framer-motion AnimatePresence)                       */}
      {/* ------------------------------------------------------------------ */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            style={{ overflow: 'hidden' }}
          >
            <div className="px-3 pb-3 pt-2 space-y-2.5">
              {/* Input row */}
              <div className="flex items-center gap-1.5">
                <input
                  className="field flex-1"
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !interpreting) void interpret();
                  }}
                  placeholder={inputPlaceholder}
                  disabled={inputDisabled}
                  autoFocus
                  aria-label="AI command input"
                />
                <button
                  className="btn btn-solid whitespace-nowrap"
                  onClick={() => void interpret()}
                  disabled={inputDisabled || interpreting || !inputText.trim()}
                  aria-label="Interpret command"
                >
                  {interpreting ? (
                    <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
                  ) : (
                    'INTERPRET'
                  )}
                </button>
                <button
                  className="btn btn-ghost"
                  onClick={() => setExpanded(false)}
                  aria-label="Close command bar"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>

              {/* Suggested prompt chips */}
              {chips.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  <span
                    className="text-[9px] uppercase tracking-[0.18em] self-center"
                    style={{ color: 'var(--od-muted)' }}
                  >
                    Suggested:
                  </span>
                  {chips.map((prompt) => (
                    <button
                      key={prompt}
                      className="chip hover:border-od-ink cursor-pointer"
                      onClick={() => onChipClick(prompt)}
                      aria-label={`Suggested prompt: ${prompt}`}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              )}

              {/* "Did this improve?" chip when cfSim is active */}
              {cfSim !== null && (
                <div className="flex">
                  <button
                    className="chip is-active cursor-pointer"
                    onClick={() => void didItHelp()}
                    aria-label="Did this improve the situation?"
                  >
                    Did this improve the situation?
                  </button>
                </div>
              )}

              {/* Loading shimmer */}
              {aiBusy && !preview && (
                <div className="space-y-1.5 py-1">
                  <div className="shimmer-line h-3 w-3/4 my-1.5" />
                  <div className="shimmer-line h-3 w-1/2 my-1.5" />
                  <div className="shimmer-line h-3 w-2/3 my-1.5" />
                </div>
              )}

              {/* Error display */}
              {aiError && (
                <div
                  className="text-[10px] px-2.5 py-1.5 border"
                  style={{
                    color: 'var(--od-danger)',
                    borderColor: 'var(--od-danger)',
                  }}
                >
                  {aiError}
                </div>
              )}

              {/* AiInterpretResponse preview card */}
              {preview && (
                <div
                  className="border px-2.5 py-2 space-y-1.5"
                  style={{
                    borderColor: 'var(--od-line)',
                    background: 'var(--od-canvas)',
                  }}
                >
                  {/* Header row */}
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className="text-[9px] uppercase tracking-[0.18em]"
                      style={{ color: 'var(--od-muted)' }}
                    >
                      Interpreted · confidence {Math.round(preview.confidence * 100)}%
                    </span>
                    {preview.provider && (
                      <span
                        className="text-[9px] uppercase tracking-[0.14em]"
                        style={{ color: 'var(--od-muted)' }}
                      >
                        {preview.provider}
                      </span>
                    )}
                  </div>

                  {/* Delta fact chips */}
                  <div className="flex flex-wrap gap-1">
                    {deltaFacts(preview.delta).map((f) => (
                      <span key={f} className="chip is-active text-[9px]">
                        {f}
                      </span>
                    ))}
                  </div>

                  {/* Reasoning */}
                  {preview.reasoning && (
                    <p
                      className="text-[10px] leading-snug"
                      style={{ color: 'var(--od-muted)' }}
                    >
                      {preview.reasoning}
                    </p>
                  )}

                  {/* Action buttons */}
                  <div className="flex gap-1.5 pt-1">
                    <button
                      className="btn btn-solid flex-1"
                      onClick={() => void runVariant(inputText.trim(), preview.delta)}
                      aria-label="Run this variant"
                    >
                      ▶ RUN THIS VARIANT
                    </button>
                    <button
                      className="btn btn-ghost"
                      onClick={() => void runVariant(inputText.trim())}
                      aria-label="Run raw"
                      title="Run without applying the interpreted delta"
                    >
                      run raw
                    </button>
                  </div>
                </div>
              )}

              {/* AiExplainResponse card */}
              {aiExplanation && (
                <div
                  className="border px-2.5 py-2 space-y-1.5"
                  style={{
                    borderColor: 'var(--od-warn)',
                    background: 'var(--od-canvas)',
                  }}
                >
                  <div
                    className="text-[9px] uppercase tracking-[0.18em]"
                    style={{ color: 'var(--od-warn)' }}
                  >
                    Grounded explanation
                    {aiExplanation.provider && (
                      <span className="ml-2 font-normal normal-case tracking-normal">
                        · {aiExplanation.provider}
                      </span>
                    )}
                  </div>

                  <p
                    className="text-[10px] leading-snug"
                    style={{ color: 'var(--od-ink)' }}
                  >
                    {aiExplanation.summary}
                  </p>

                  <p
                    className="text-[10px] leading-snug"
                    style={{ color: 'var(--od-muted)' }}
                  >
                    Cause: {aiExplanation.cause}
                  </p>

                  {aiExplanation.try_actions.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {aiExplanation.try_actions.map((a) => (
                        <span key={a.description} className="chip text-[9px]">
                          {a.description}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
