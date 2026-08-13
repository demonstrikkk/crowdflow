import { useMemo } from 'react';
import type { SimulationState, VenueModel } from '../../lib/types';
import { computeDelta, deltaColor } from '../../lib/delta';
import { positionsOf } from '../../lib/selection';

/**
 * DeltaInstrumentCanvas — spatial delta view between baseline and counterfactual.
 *
 * Requirements: Req 7, Req 8, Req 21
 * - Renders venue geometry in muted style (30% opacity) as context
 * - Overlays DeltaEntry colours on edges/nodes with |densityDelta| > 0.03
 * - Bottom-left legend: density decreased (green), density increased (red), flow redistributed (blue)
 */

interface DeltaCanvasProps {
  baseSim: SimulationState;
  cfSim: SimulationState;
  venue: VenueModel;
}

export function DeltaInstrumentCanvas({ baseSim, cfSim, venue }: DeltaCanvasProps) {
  const W = venue.width;
  const H = venue.height;
  const m = Math.min(W, H);
  const nodeR = m / 46;

  // Node positions from baseSim node_positions or venue model fallback
  const pos = useMemo(
    () => positionsOf(venue, baseSim.node_positions),
    [venue, baseSim.node_positions],
  );

  // Compute spatial delta (Req 8)
  const deltas = useMemo(() => computeDelta(baseSim, cfSim), [baseSim, cfSim]);

  // Build lookup maps for quick access
  const deltaMap = useMemo(() => {
    const m = new Map<string, (typeof deltas)[number]>();
    for (const d of deltas) m.set(d.id, d);
    return m;
  }, [deltas]);

  const viewBox = `0 0 ${W} ${H}`;

  return (
    <div className="relative h-full w-full overflow-hidden bg-od-canvas">
      <svg
        viewBox={viewBox}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full"
        role="img"
        aria-label="Delta view — spatial difference between baseline and counterfactual"
      >
        {/* Floor background */}
        <rect x="0" y="0" width={W} height={H} fill="var(--od-canvas)" />
        <rect x="0" y="0" width={W} height={H} fill="none" stroke="var(--od-line)" strokeWidth={m / 500} opacity={0.4} />

        {/* ── Muted venue geometry (30% opacity) ─────────────────────── */}
        <g opacity={0.3}>
          {venue.edges.map((e) => {
            const s = pos.get(e.source);
            const d = pos.get(e.destination);
            if (!s || !d) return null;
            return (
              <line
                key={`${e.source}→${e.destination}`}
                x1={s.x} y1={s.y} x2={d.x} y2={d.y}
                stroke="var(--od-line)"
                strokeWidth={m / 450}
              />
            );
          })}
          {venue.nodes.map((n) => {
            const p = pos.get(n.id);
            if (!p) return null;
            return (
              <circle
                key={n.id}
                cx={p.x} cy={p.y}
                r={n.type === 'ZONE' ? nodeR * 1.8 : nodeR}
                fill="none"
                stroke="var(--od-line)"
                strokeWidth={m / 400}
              />
            );
          })}
        </g>

        {/* ── Delta overlays ───────────────────────────────────────────── */}
        {venue.edges.map((e) => {
          const key = `${e.source}→${e.destination}`;
          const delta = deltaMap.get(key);
          if (!delta || Math.abs(delta.densityDelta) <= 0.03) return null;

          const s = pos.get(e.source);
          const d = pos.get(e.destination);
          if (!s || !d) return null;

          const color = deltaColor(delta.densityDelta, delta.flowDelta);
          const magnitude = Math.min(1, Math.abs(delta.densityDelta) / 0.3);
          const strokeWidth = (m / 450) + magnitude * (m / 120);
          const opacity = 0.5 + magnitude * 0.5;

          return (
            <line
              key={`delta-edge-${key}`}
              x1={s.x} y1={s.y} x2={d.x} y2={d.y}
              stroke={color}
              strokeWidth={strokeWidth}
              opacity={opacity}
              strokeLinecap="round"
            />
          );
        })}

        {venue.nodes.map((n) => {
          const delta = deltaMap.get(n.id);
          if (!delta || Math.abs(delta.densityDelta) <= 0.03) return null;

          const p = pos.get(n.id);
          if (!p) return null;

          const color = deltaColor(delta.densityDelta, delta.flowDelta);
          const magnitude = Math.min(1, Math.abs(delta.densityDelta) / 0.3);
          const r = nodeR * (0.8 + magnitude * 0.8);
          const opacity = 0.5 + magnitude * 0.5;

          return (
            <circle
              key={`delta-node-${n.id}`}
              cx={p.x} cy={p.y}
              r={r}
              fill={color}
              opacity={opacity}
            />
          );
        })}

        {/* ── Bottom-left legend ───────────────────────────────────────── */}
        <g transform={`translate(${m * 0.03}, ${H - m * 0.09})`}>
          <rect
            x={-m * 0.01}
            y={-m * 0.055}
            width={m * 0.62}
            height={m * 0.08}
            fill="var(--od-panel)"
            opacity={0.85}
            rx={2}
          />
          {/* Density decreased */}
          <rect x={0} y={-m * 0.022} width={m * 0.04} height={m * 0.014} fill="hsl(142, 70%, 45%)" rx={1} />
          <text x={m * 0.05} y={-m * 0.01} fontSize={Math.max(6, m / 70)} fill="var(--od-muted)" dominantBaseline="middle">
            Density decreased
          </text>
          {/* Density increased */}
          <rect x={m * 0.2} y={-m * 0.022} width={m * 0.04} height={m * 0.014} fill="hsl(0, 70%, 50%)" rx={1} />
          <text x={m * 0.25} y={-m * 0.01} fontSize={Math.max(6, m / 70)} fill="var(--od-muted)" dominantBaseline="middle">
            Density increased
          </text>
          {/* Flow redistributed */}
          <rect x={m * 0.4} y={-m * 0.022} width={m * 0.04} height={m * 0.014} fill="hsl(210, 70%, 55%)" rx={1} />
          <text x={m * 0.45} y={-m * 0.01} fontSize={Math.max(6, m / 70)} fill="var(--od-muted)" dominantBaseline="middle">
            Flow redistributed
          </text>
        </g>
      </svg>
    </div>
  );
}

export default DeltaInstrumentCanvas;
