import { ArrowRight, X } from 'lucide-react';

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
    <div className="absolute top-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-3 border border-od-warn bg-od-panel px-3 py-2 shadow-[0_16px_48px_-24px_rgba(0,0,0,0.7)]">
      <span className="status-dot is-warn" />
      <div>
        <div className="sec-label">Bottleneck forming</div>
        <div className="num mt-0.5 text-[12px] font-bold text-od-ink">{location}</div>
      </div>
      <button className="btn btn-solid gap-1.5" onClick={onAct}>
        SEE WHAT WE CAN CHANGE
        <ArrowRight className="h-3 w-3" />
      </button>
      <button
        className="btn btn-ghost"
        onClick={onDismiss}
        aria-label="Dismiss guidance"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
