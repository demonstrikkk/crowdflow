import type {
  AiExplainResponse,
  Bottleneck,
  EdgeModel,
  ElementState,
  Intervention,
  InterventionType,
  NodeModel,
  RiskLevel,
  SimulationState,
  VenueModel,
} from '../../lib/types';
import { quickActionsFor } from '../../lib/quickActions';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface BottleneckInvestigationPanelProps {
  bottleneck: Bottleneck;
  elementState: ElementState;
  venueElement: EdgeModel | NodeModel;
  sim: SimulationState;
  venue: VenueModel;
  onDraftIntervention: (i: Intervention) => void;
  onExplainAi: () => void;
  aiExplanation: AiExplainResponse | null;
  aiBusy: boolean;
  aiConfigured: boolean | null;
  aiError: string | null;
}

// ---------------------------------------------------------------------------
// Helper: format numbers
// ---------------------------------------------------------------------------

function fmt(n: number | undefined | null, digits = 0): string {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

// ---------------------------------------------------------------------------
// Helper: risk badge chip
// ---------------------------------------------------------------------------

function riskChipClass(risk: RiskLevel): string {
  switch (risk) {
    case 'CRITICAL':
      return 'chip is-danger';
    case 'HIGH':
      return 'chip is-danger';
    case 'ELEVATED':
      return 'chip is-warn';
    default:
      return 'chip is-ok';
  }
}

function RiskBadge({ risk }: { risk: RiskLevel }) {
  return (
    <span className={riskChipClass(risk)}>
      <span
        className={`status-dot ${
          risk === 'CRITICAL' || risk === 'HIGH'
            ? 'is-danger'
            : risk === 'ELEVATED'
            ? 'is-warn'
            : 'is-ok'
        }`}
      />
      {risk}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Helper: progress bar color by risk
// ---------------------------------------------------------------------------

function utilisationBarColor(risk: RiskLevel): string {
  switch (risk) {
    case 'CRITICAL':
      return 'var(--od-danger)';
    case 'HIGH':
      return 'var(--od-danger)';
    case 'ELEVATED':
      return 'var(--od-warn)';
    default:
      return 'var(--od-ok)';
  }
}

// ---------------------------------------------------------------------------
// WHY block helper: routeConcentration
// ---------------------------------------------------------------------------

/**
 * Count agents whose route array contains the consecutive src→dst pair.
 * Returns count / sim.agents.length (0 when no agents).
 */
function routeConcentration(sim: SimulationState, edgeId: string): number {
  const [src, dst] = edgeId.split('→');
  if (!src || !dst) return 0;
  if (sim.agents.length === 0) return 0;

  let count = 0;
  for (const agent of sim.agents) {
    const route = agent.route;
    for (let i = 0; i < route.length - 1; i++) {
      if (route[i] === src && route[i + 1] === dst) {
        count++;
        break;
      }
    }
  }
  return count / sim.agents.length;
}

// ---------------------------------------------------------------------------
// IMPACT block helper: cascadeEdges
// ---------------------------------------------------------------------------

function cascadeEdges(
  bottleneck: Bottleneck,
  venue: VenueModel,
  sim: SimulationState,
): { id: string; risk: RiskLevel; name: string }[] {
  const [src, dst] = bottleneck.location.split('→');
  return venue.edges
    .filter((e) => e.source === dst || e.destination === src)
    .map((e) => {
      const key = `${e.source}→${e.destination}`;
      const st = sim.edges[key];
      return { id: key, risk: (st?.risk ?? 'NORMAL') as RiskLevel, name: key };
    })
    .filter((e) => e.risk !== 'NORMAL');
}

// ---------------------------------------------------------------------------
// Sub-section header
// ---------------------------------------------------------------------------

function BlockHeader({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 pb-1.5">
      <span className="text-[9px] font-bold uppercase tracking-[0.2em] text-od-danger">{label}</span>
      <span className="h-px flex-1 bg-od-line" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function BottleneckInvestigationPanel({
  bottleneck,
  elementState,
  sim,
  venue,
  onDraftIntervention,
  onExplainAi,
  aiExplanation,
  aiBusy,
  aiConfigured,
  aiError,
}: BottleneckInvestigationPanelProps) {
  // ── derived values ────────────────────────────────────────────────────────
  const utilPct = Math.min(100, Math.round(elementState.utilisation * 100));
  const barColor = utilisationBarColor(elementState.risk);
  const ttc = elementState.time_to_critical_min;

  const concentration = routeConcentration(sim, bottleneck.location);
  const concentrationPct = Math.round(concentration * 100);

  const demandGapPct =
    elementState.capacity > 0
      ? Math.round(
          ((elementState.flow_per_min - elementState.capacity) / elementState.capacity) * 100,
        )
      : 0;

  const cascades = cascadeEdges(bottleneck, venue, sim);

  const quickActions = quickActionsFor(bottleneck, venue, sim);

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">

      {/* ── WHAT block ─────────────────────────────────────────────────── */}
      <section>
        <BlockHeader label="WHAT" />

        {/* Location + risk badge */}
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="min-w-0">
            <div className="num truncate text-[13px] font-bold uppercase tracking-[0.04em] text-od-ink leading-tight">
              {bottleneck.location.replace(/→/g, ' → ')}
            </div>
            <div className="meta mt-0.5">
              {bottleneck.kind === 'edge' ? 'CORRIDOR' : 'NODE'}
            </div>
          </div>
          <RiskBadge risk={bottleneck.current_risk} />
        </div>

        {/* Metrics row */}
        <div className="grid grid-cols-3 gap-x-3 gap-y-2 border-t border-od-line pt-2.5">
          <div>
            <div className="meta">Density</div>
            <div className="num mt-0.5 text-od-ink">{fmt(elementState.density, 2)}<span className="text-od-muted text-[9px]"> /m²</span></div>
          </div>
          <div>
            <div className="meta">Flow/min</div>
            <div className="num mt-0.5 text-od-ink">{fmt(elementState.flow_per_min)}</div>
          </div>
          <div>
            <div className="meta">Queue</div>
            <div className="num mt-0.5 text-od-ink">{fmt(elementState.queue)}</div>
          </div>
        </div>

        {/* Utilisation progress bar */}
        <div className="mt-2.5 space-y-1">
          <div className="flex items-center justify-between">
            <span className="meta">Utilisation</span>
            <span className="num text-od-ink mono-tabular">{utilPct}%</span>
          </div>
          <div className="h-1.5 w-full rounded-none bg-od-line overflow-hidden">
            <div
              className="h-full transition-all duration-300"
              style={{
                width: `${utilPct}%`,
                backgroundColor: barColor,
              }}
            />
          </div>
          <div className="flex justify-between text-[9px] text-od-muted mono-tabular">
            <span>0</span>
            <span>Capacity {fmt(elementState.capacity)}</span>
          </div>
        </div>

        {/* Time-to-critical */}
        {ttc != null && (
          <div className="mt-2.5 flex items-center gap-1.5 border border-od-warn bg-od-warn-soft px-2.5 py-1.5">
            <span className="text-od-warn text-[11px]">⚠</span>
            <span className="text-[10px] uppercase tracking-[0.12em] text-od-warn font-bold">
              Time-to-critical:
            </span>
            <span className="num text-od-warn mono-tabular">{ttc.toFixed(1)} min</span>
          </div>
        )}
      </section>

      {/* ── WHY block ──────────────────────────────────────────────────── */}
      <section>
        <BlockHeader label="WHY" />

        {/* Route concentration */}
        <div className="space-y-1.5 text-[11px] leading-snug text-od-ink">
          <p>
            <span className="num font-bold">{concentrationPct}%</span>
            <span className="text-od-muted"> of active agents route through this corridor.</span>
          </p>

          {/* Demand vs capacity */}
          <div className="border-t border-od-line pt-1.5 flex flex-wrap gap-x-4 gap-y-1 mono-tabular text-[10px]">
            <span className="text-od-muted">
              Demand: <span className="text-od-ink">{fmt(elementState.flow_per_min)}/min</span>
            </span>
            <span className="text-od-muted">
              Capacity: <span className="text-od-ink">{fmt(elementState.capacity)}/min</span>
            </span>
          </div>
          {demandGapPct > 0 && (
            <p className="text-od-danger text-[10px]">
              Demand exceeds safe throughput by {demandGapPct}%.
            </p>
          )}

          {/* Engine explanation */}
          {bottleneck.explanation && (
            <p className="border-t border-od-line pt-1.5 text-[10px] leading-snug text-od-muted italic">
              {bottleneck.explanation}
            </p>
          )}
        </div>
      </section>

      {/* ── IMPACT block ───────────────────────────────────────────────── */}
      <section>
        <BlockHeader label="IMPACT" />

        {/* Time-to-critical summary */}
        <div className="text-[11px] text-od-muted mb-1.5">
          {ttc != null ? (
            <span>
              Time to critical:{' '}
              <span className="text-od-warn font-bold">⚠ {ttc.toFixed(1)} min</span>
              {' '}at current trend
            </span>
          ) : (
            <span>No imminent critical threshold at current trend.</span>
          )}
        </div>

        {/* Cascade list */}
        {cascades.length === 0 ? (
          <p className="text-[10px] text-od-muted">No elevated cascade risk on connected corridors.</p>
        ) : (
          <div className="space-y-1">
            <p className="text-[10px] text-od-muted mb-1">
              Cascade risk: <span className="text-od-ink font-bold">{cascades.length}</span> connected corridor{cascades.length !== 1 ? 's' : ''} elevated
            </p>
            {cascades.map((c) => (
              <div
                key={c.id}
                className="flex items-center justify-between px-2 py-1 border border-od-line border-l-2 border-l-od-warn text-[10px]"
              >
                <span className="truncate text-od-ink mono-tabular">{c.name.replace(/→/g, ' → ')}</span>
                <RiskBadge risk={c.risk} />
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Quick actions ───────────────────────────────────────────────── */}
      <section>
        <BlockHeader label="ACTIONS" />
        <div className="space-y-1.5">
          {quickActions.map((action, i) => {
            // Determine border color by variant
            const borderClass =
              action.variant === 'warn'
                ? 'border-od-danger hover:bg-od-danger-soft'
                : action.variant === 'ok'
                ? 'border-od-ok hover:bg-od-ok-soft'
                : 'border-od-line hover:border-od-ink';

            return (
              <button
                key={i}
                className={`w-full border ${borderClass} text-left px-2.5 py-2 cursor-pointer transition-colors`}
                onClick={() => {
                  onDraftIntervention({
                    id: crypto.randomUUID(),
                    ...action.intervention,
                  });
                }}
              >
                <div
                  className={`text-[10px] font-bold uppercase tracking-[0.12em] ${
                    action.variant === 'warn'
                      ? 'text-od-danger'
                      : action.variant === 'ok'
                      ? 'text-od-ok'
                      : 'text-od-ink'
                  }`}
                >
                  {action.label}
                </div>
                {action.description && (
                  <div className="mt-0.5 text-[10px] leading-snug text-od-muted">
                    {action.description}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </section>

      {/* ── AI explain button ───────────────────────────────────────────── */}
      <section>
        <button
          className="btn btn-solid w-full"
          onClick={onExplainAi}
          disabled={aiConfigured === false || aiBusy}
          title={aiConfigured === false ? 'Configure AI in Settings' : undefined}
        >
          🧠 AI: What can I do?
        </button>

        {/* AI loading shimmer */}
        {aiBusy && (
          <div className="mt-2.5 space-y-1.5">
            <div className="shimmer-line" style={{ height: 12 }} />
            <div className="shimmer-line" style={{ height: 10 }} />
            <div className="shimmer-line" style={{ height: 10, width: '75%' }} />
          </div>
        )}

        {/* AI failure — never silently fall back */}
        {!aiBusy && aiError && (
          <div className="mt-2.5 border border-od-danger bg-od-danger-soft px-2.5 py-2" role="alert">
            <div className="flex items-center gap-2">
              <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-od-danger">
                AI request failed
              </span>
            </div>
            <p className="mt-1 text-[10px] leading-snug text-od-danger">{aiError}</p>
            <button
              className="btn btn-ghost mt-1.5 !border-od-danger !text-od-danger"
              onClick={onExplainAi}
            >
              Retry
            </button>
          </div>
        )}

        {/* AI not configured */}
        {!aiBusy && !aiError && aiConfigured === false && (
          <div className="mt-2.5 border border-od-warn bg-od-warn-soft px-2.5 py-2" role="status">
            <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-od-warn">
              AI unavailable
            </span>
            <p className="mt-1 text-[10px] leading-snug text-od-muted">
              No AI provider configured. Add GROQ_API_KEY / provider settings to enable analysis.
            </p>
          </div>
        )}

        {/* AI explanation response */}
        {!aiBusy && aiExplanation && (
          <div className="mt-2.5 border border-od-warn bg-od-warn-soft px-2.5 py-2 space-y-2">
            {/* Header row: provider */}
            <div className="flex items-center justify-between">
              <span className="text-[9px] uppercase tracking-[0.18em] text-od-warn font-bold">
                AI Explanation
              </span>
              {aiExplanation.provider && (
                <span className="text-[9px] text-od-muted uppercase tracking-[0.12em]">
                  {aiExplanation.provider}
                </span>
              )}
            </div>

            {/* Summary */}
            {aiExplanation.summary && (
              <p className="text-[11px] leading-snug text-od-ink">{aiExplanation.summary}</p>
            )}

            {/* Cause */}
            {aiExplanation.cause && (
              <p className="text-[10px] leading-snug text-od-muted">
                <span className="text-od-muted font-semibold">Cause: </span>
                {aiExplanation.cause}
              </p>
            )}

            {/* Try actions as clickable chips */}
            {aiExplanation.try_actions.length > 0 && (
              <div>
                <div className="text-[9px] uppercase tracking-[0.15em] text-od-muted mb-1">Try:</div>
                <div className="flex flex-wrap gap-1">
                  {aiExplanation.try_actions.map(
                    (
                      action: {
                        type: InterventionType;
                        description: string;
                        parameters: Record<string, unknown>;
                      },
                      idx: number,
                    ) => (
                      <button
                        key={idx}
                        className="chip hover:is-active cursor-pointer"
                        onClick={() => {
                          onDraftIntervention({
                            id: crypto.randomUUID(),
                            type: action.type,
                            description: action.description,
                            parameters: action.parameters,
                          });
                        }}
                        title={action.description}
                      >
                        {action.description}
                      </button>
                    ),
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

export default BottleneckInvestigationPanel;
