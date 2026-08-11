export default function EmptyState({
  venueName,
  onLoad,
  onBuild,
  onImport,
  hasScenario,
}: {
  venueName: string | null;
  onLoad: () => void;
  onBuild: () => void;
  onImport: () => void;
  hasScenario: boolean;
}) {
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-od-canvas/70 p-4">
      <div className="w-full max-w-md border border-od-line bg-od-panel shadow-[0_32px_80px_-40px_rgba(0,0,0,0.8)]">
        <div className="flex items-center justify-between border-b border-od-line px-6 py-3">
          <span className="sec-label truncate" title={venueName ?? undefined}>
            {venueName ?? 'Digital twin'}
          </span>
          <span className="chip is-active">
            <span className="status-dot is-ok" />
            Operational twin
          </span>
        </div>

        <div className="space-y-5 px-6 py-6">
          <div>
            <h1 className="font-display text-xl font-extrabold uppercase tracking-[0.04em] text-od-ink">
              The venue is live.
            </h1>
            <p className="mt-2 max-w-[400px] text-[12px] leading-relaxed text-od-muted">
              Introduce a situation — an event, an incident, a constraint — and watch the system evolve on
              the venue. Then intervene, and compare the outcome.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {['VENUE', 'SITUATION', 'SIMULATE', 'INTERVENE', 'OUTCOME'].map((step, i) => (
              <span key={step} className={`chip ${i === 0 ? 'is-active' : ''}`}>
                {i === 0 ? '● ' : ''}
                {step}
                {i < 4 ? ' →' : ''}
              </span>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t border-od-line pt-5">
            <button className="btn btn-solid" onClick={onLoad} disabled={!hasScenario}>
              {hasScenario ? 'RUN EVENT SIMULATION' : 'CHOOSE AN EVENT'}
            </button>
            <button className="btn btn-ghost" onClick={onBuild}>
              BUILD A SITUATION
            </button>
            <button className="btn btn-ghost" onClick={onImport}>
              CHANGE TWIN
            </button>
          </div>
          {!hasScenario && (
            <p className="text-[10px] uppercase tracking-[0.14em] text-od-muted">
              No event selected — build one to run a simulation.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
