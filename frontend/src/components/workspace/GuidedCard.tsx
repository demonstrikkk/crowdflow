export default function GuidedCard({
  location,
  onAct,
  onDismiss,
}: {
  location: string;
  onAct: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10 flex items-center gap-3 border border-od-warn bg-od-panel px-3 py-2 shadow-sm">
      <span className="status-dot is-warn" />
      <div>
        <div className="text-[9px] uppercase tracking-[0.2em] text-od-muted">Bottleneck forming</div>
        <div className="num">{location}</div>
      </div>
      <button className="btn btn-solid" onClick={onAct}>
        SEE WHAT WE CAN CHANGE
      </button>
      <button
        className="btn btn-ghost"
        onClick={onDismiss}
        aria-label="Dismiss guidance"
      >
        ✕
      </button>
    </div>
  );
}