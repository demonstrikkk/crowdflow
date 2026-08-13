import type { Bottleneck, VenueModel } from '../../lib/types';

/**
 * BottleneckPulseLayer — SVG layer for animated pulse rings at bottleneck locations.
 *
 * Requirements: Req 5
 * - Renders two concentric rings per bottleneck with CSS keyframe animation (Req 5.1, 5.2, 5.5)
 * - Ring color: var(--od-danger) for CRITICAL, var(--od-warn) for HIGH (Req 5.3)
 * - "BOTTLENECK" text badge above midpoint (Req 5.4)
 * - Returns empty SVG when bottlenecks.length === 0 (Req 5.6)
 * - All animation via CSS (App.css Task 4) — no JS animation (Req 5.5)
 */

interface BottleneckPulseLayerProps {
  bottlenecks: Bottleneck[];
  venue: VenueModel;
  nodePositions: Map<string, { x: number; y: number }>;
  viewBox: string;
}

function getEdgeMidpoint(
  location: string,
  nodePositions: Map<string, { x: number; y: number }>,
): { x: number; y: number } | null {
  // Edge format: "SRC→DST" or "SRC->DST"
  const parts = location.split(/→|->|→/);
  if (parts.length === 2) {
    const a = nodePositions.get(parts[0].trim());
    const b = nodePositions.get(parts[1].trim());
    if (a && b) return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    // If destination unknown, use source
    if (a) return a;
  }
  // Node fallback
  const pos = nodePositions.get(location);
  return pos ?? null;
}

export function BottleneckPulseLayer({
  bottlenecks,
  nodePositions,
  viewBox,
  venue,
}: BottleneckPulseLayerProps) {
  const m = Math.min(venue.width, venue.height);
  const ringR = m / 40;
  const fontSize = Math.max(7, m / 56);

  return (
    <svg
      viewBox={viewBox}
      preserveAspectRatio="xMidYMid meet"
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 4,
        overflow: 'visible',
      }}
      aria-hidden="true"
    >
      {bottlenecks.map((b) => {
        const mid = getEdgeMidpoint(b.location, nodePositions);
        if (!mid) return null;

        const fill =
          b.current_risk === 'CRITICAL' ? 'var(--od-danger)' : 'var(--od-warn)';

        return (
          <g key={b.id} pointerEvents="none">
            {/* Two concentric rings — CSS keyframes handle the pulse animation (Req 5.2) */}
            <circle
              cx={mid.x}
              cy={mid.y}
              r={ringR}
              fill={fill}
              opacity={0.8}
              className="od-bottleneck-pulse"
            />
            <circle
              cx={mid.x}
              cy={mid.y}
              r={ringR}
              fill={fill}
              opacity={0.6}
              className="od-bottleneck-pulse-delay"
            />
            {/* Static inner dot for visibility */}
            <circle cx={mid.x} cy={mid.y} r={ringR * 0.25} fill={fill} opacity={0.9} />
            {/* BOTTLENECK text badge above midpoint (Req 5.4) */}
            <text
              x={mid.x}
              y={mid.y - ringR - 4}
              textAnchor="middle"
              fontSize={fontSize}
              fontWeight={800}
              fill={fill}
              letterSpacing="0.10em"
              style={{ textTransform: 'uppercase' }}
            >
              BOTTLENECK
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default BottleneckPulseLayer;
