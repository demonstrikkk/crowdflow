export default function EmptyState({
  onLoad,
  onBuild,
  onImport,
  hasScenario,
}: {
  onLoad: () => void;
  onBuild: () => void;
  onImport: () => void;
  hasScenario: boolean;
}) {
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-od-canvas/70 px-4">
      <div className="w-full max-w-md border border-od-line bg-od-panel px-6 py-7 text-center">
        <div className="text-[10px] uppercase tracking-[0.3em] text-od-muted">Crowd Operations</div>
        <h1 className="font-display text-lg font-bold uppercase tracking-[0.08em] text-od-ink">
          What do you want to test?
        </h1>
        <p className="mx-auto mt-1.5 max-w-[380px] text-[12px] text-od-muted leading-relaxed">
          The venue below is live. Run an event scenario against it, investigate where congestion
          forms, intervene, and compare the outcome against a counterfactual.
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <button className="btn btn-solid" onClick={onLoad} disabled={!hasScenario}>
            LOAD EVENT SCENARIO
          </button>
          <button className="btn btn-ghost" onClick={onBuild}>
            BUILD A SCENARIO
          </button>
          <button className="btn btn-ghost" onClick={onImport}>
            IMPORT VENUE
          </button>
        </div>
      </div>
    </div>
  );
}
