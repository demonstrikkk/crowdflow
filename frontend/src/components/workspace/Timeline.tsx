import { useRef, useState } from 'react';
import { Pause, Play, RotateCcw } from 'lucide-react';
import type { PlaybackFrame } from '../../store/SimulationContext';
import type { EventPhaseModel } from '../../lib/types';

export interface TimelineMarker {
  t: number;
  label: string;
  tone: 'danger' | 'warn' | 'ok' | 'active';
}

export interface TimelineProps {
  buffer: PlaybackFrame[];
  frameIndex: number;
  seeking: boolean;
  tMin: number;
  status: string;
  phases: EventPhaseModel[];
  speed: number;
  speeds: number[];
  onSeek: (i: number) => void;
  onJump: (minute: number) => void;
  onPlay: () => void;
  onPause: () => void;
  onRewind: () => void;
  onSpeed: (s: number) => void;
  simId: string | null;
  markers?: TimelineMarker[];
}

const PHASE_TONE: Record<string, string> = {
  ENTRY: 'var(--od-line)',
  PEAK: 'var(--od-warn)',
  INTERVAL: 'var(--od-line)',
  EXIT_SURGE: 'var(--od-danger)',
};

const MARKER_TONE: Record<TimelineMarker['tone'], string> = {
  danger: 'var(--od-danger)',
  warn: 'var(--od-warn)',
  ok: 'var(--od-ok)',
  active: 'var(--od-active, #8d6be8)',
};

export default function Timeline({
  buffer,
  frameIndex,
  seeking,
  tMin,
  status,
  phases,
  speed,
  speeds,
  onSeek,
  onJump,
  onPlay,
  onPause,
  onRewind,
  onSpeed,
  simId,
  markers = [],
}: TimelineProps) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [drag, setDrag] = useState<number | null>(null);

  const bufferStart = buffer.length > 0 ? buffer[0].t : 0;
  const bufferEnd = buffer.length > 0 ? buffer[buffer.length - 1].t : 0;
  const lastPhaseEnd = phases.reduce((acc, p) => Math.max(acc, p.end_minute), 0);
  const span = Math.max(lastPhaseEnd, bufferEnd, 1);
  const live = tMin;

  const shown =
    drag != null
      ? drag
      : seeking && frameIndex >= 0 && buffer[frameIndex]
        ? buffer[frameIndex].t
        : live;

  const pct = Math.min(100, (shown / span) * 100);

  const minuteFromClientX = (clientX: number) => {
    const el = trackRef.current;
    if (!el) return 0;
    const rect = el.getBoundingClientRect();
    const rel = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return rel * span;
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (!simId) return;
    const t = minuteFromClientX(e.clientX);
    setDrag(t);
    if (t >= bufferStart && t <= bufferEnd && buffer.length > 0) {
      let idx = buffer.length - 1;
      for (let i = 0; i < buffer.length; i++) {
        if (buffer[i].t >= t) {
          idx = i;
          break;
        }
      }
      onSeek(idx);
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (drag == null || !simId) return;
    const t = minuteFromClientX(e.clientX);
    setDrag(t);
    if (t >= bufferStart && t <= bufferEnd && buffer.length > 0) {
      let idx = buffer.length - 1;
      for (let i = 0; i < buffer.length; i++) {
        if (buffer[i].t >= t) {
          idx = i;
          break;
        }
      }
      onSeek(idx);
    }
  };

  const onPointerUp = () => {
    if (drag == null) return;
    const t = drag;
    setDrag(null);
    if (t < bufferStart - 0.001 || t > bufferEnd + 0.001) {
      onJump(Math.round(t));
    }
  };

  const playing = status === 'RUNNING' && !seeking;

  return (
    <div className="border-t border-od-line bg-od-panel px-3 pt-2 pb-2 select-none" role="region" aria-label="Timeline">
      <div
        ref={trackRef}
        className="relative h-7 cursor-pointer touch-none"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        {/* phase bands */}
        {phases.map((p) => (
          <div
            key={p.name}
            className="absolute top-1 bottom-1 rounded-[1px]"
            style={{
              left: `${(p.start_minute / span) * 100}%`,
              width: `${((p.end_minute - p.start_minute) / span) * 100}%`,
              background: PHASE_TONE[p.name] ?? 'var(--od-line)',
              opacity: 0.18,
            }}
            title={`${p.name} ${p.start_minute}–${p.end_minute} min`}
          />
        ))}

        {/* recorded window */}
        {buffer.length > 1 && (
          <div
            className="absolute top-0.5 bottom-0.5 bg-od-ok opacity-10"
            style={{ left: `${(bufferStart / span) * 100}%`, width: `${((bufferEnd - bufferStart) / span) * 100}%` }}
          />
        )}

        {/* grid ticks */}
        {Array.from({ length: 9 }).map((_, i) => (
          <div key={i} className="absolute top-0 bottom-0 w-px bg-od-line" style={{ left: `${(i / 8) * 100}%`, opacity: 0.35 }} />
        ))}

        {/* incident markers */}
        {markers.map((m) => (
          <div
            key={`${m.t}-${m.label}`}
            className="absolute top-0 z-[1] flex h-full items-center"
            style={{ left: `${Math.min(100, (m.t / span) * 100)}%` }}
            title={`${m.t.toFixed(1)} min — ${m.label}`}
          >
            <div className="h-2.5 w-2.5 rotate-45 border border-black/30" style={{ background: MARKER_TONE[m.tone] }} />
          </div>
        ))}

        {/* playhead */}
        <div
          className="absolute top-0 bottom-0 w-[2px] bg-od-ink"
          style={{ left: `calc(${pct}% - 1px)`, opacity: drag != null ? 0.9 : 0.75 }}
        >
          <div className="absolute -top-0.5 left-1/2 -translate-x-1/2 w-2 h-2 rounded-full bg-od-ink" />
        </div>

        <div className="absolute left-0 bottom-[-2px] sec-label mono-tabular">
          {shown.toFixed(1)} min
        </div>
        <div className="absolute right-0 bottom-[-2px] sec-label mono-tabular">
          {span.toFixed(0)} min
        </div>
      </div>

      {/* controls */}
      <div className="flex items-center gap-1.5 pt-2.5">
        <button
          className="btn btn-ghost"
          onClick={onRewind}
          disabled={!simId}
          title="Rewind to start"
          aria-label="Rewind to start"
        >
          <RotateCcw className="h-3 w-3" /> REWIND
        </button>
        <button className="btn btn-solid" onClick={playing ? onPause : onPlay} disabled={!simId} aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
          {playing ? 'PAUSE' : 'PLAY'}
        </button>
        <span className="w-px h-4 bg-od-line mx-1" />
        {speeds.map((s) => (
          <button
            key={s}
            className={`btn ${speed === s ? 'btn-solid' : 'btn-ghost'}`}
            onClick={() => onSpeed(s)}
          >
            ×{s}
          </button>
        ))}
        <span className="flex-1" />
        {markers.length > 0 && (
          <div className="flex items-center gap-1">
            {markers.slice(-6).map((m) => (
              <button
                key={`chip-${m.t}-${m.label}`}
                className="chip"
                title={`${m.t.toFixed(1)} min`}
                onClick={() => onJump(Math.round(m.t))}
                disabled={!simId}
              >
                <span className="w-1.5 h-1.5 rotate-45 inline-block" style={{ background: MARKER_TONE[m.tone] }} />
                {m.label}
              </button>
            ))}
          </div>
        )}
        <span className="text-[9px] uppercase tracking-[0.18em] text-od-muted mr-1">Event</span>
        <div className="flex items-center gap-1">
          {phases.map((p) => (
            <button
              key={p.name}
              className="chip"
              title={`Jump to ${p.name} start (${p.start_minute} min)`}
              onClick={() => onJump(p.start_minute)}
              disabled={!simId}
            >
              <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ background: PHASE_TONE[p.name] ?? 'var(--od-line)' }} />
              {p.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}