import { useMemo, useRef } from 'react';
import type { SimulationState, VenueModel } from '../../lib/types';
import { edgeKey } from '../../lib/selection';

/**
 * FlowArrowLayer — SVG layer for directional flow arrows on corridors.
 *
 * Requirements: Req 4
 * - Only renders arrows where flow_per_min > 5 (Req 4.1 / 4.2)
 * - opacity = 0.4 + magnitude * 0.5; magnitude = flow_per_min / capacity [0,1] (Req 4.3)
 * - color: var(--od-warn) when magnitude > 0.7, else var(--od-soft) (Req 4.4)
 * - Throttled to every 3rd WS frame (~10fps at 30fps WS) (Req 4.5)
 */

interface FlowArrowLayerProps {
  sim: SimulationState | null;
  venue: VenueModel;
  nodePositions: Map<string, { x: number; y: number }>;
  viewBox: string;
}

export function FlowArrowLayer({ sim, venue, nodePositions, viewBox }: FlowArrowLayerProps) {
  const frameCounter = useRef(0);
  const cachedArrows = useRef<JSX.Element[]>([]);

  const arrows = useMemo(() => {
    if (!sim) return [];

    // Throttle: only recompute on every 3rd render (Req 4.5)
    frameCounter.current++;
    if (frameCounter.current % 3 !== 0) return cachedArrows.current;

    const result: JSX.Element[] = [];

    for (const edge of venue.edges) {
      const key = edgeKey(edge.source, edge.destination);
      const st = sim.edges[key];
      if (!st || st.flow_per_min <= 5) continue; // Req 4.2

      const srcPos = nodePositions.get(edge.source);
      const dstPos = nodePositions.get(edge.destination);
      if (!srcPos || !dstPos) continue;

      const midX = (srcPos.x + dstPos.x) / 2;
      const midY = (srcPos.y + dstPos.y) / 2;
      const angleDeg = (Math.atan2(dstPos.y - srcPos.y, dstPos.x - srcPos.x) * 180) / Math.PI;

      const magnitude = Math.min(1, st.flow_per_min / Math.max(1, edge.capacity)); // Req 4.3
      const opacity = 0.4 + magnitude * 0.5;
      const color = magnitude > 0.7 ? 'var(--od-warn)' : 'var(--od-soft)'; // Req 4.4

      const arrowSize = 8;
      // Arrowhead pointing right (→), rotated to direction
      const arrowPath = `M0,0 L${-arrowSize},${-arrowSize * 0.5} L${-arrowSize * 0.75},0 L${-arrowSize},${arrowSize * 0.5} Z`;

      result.push(
        <g
          key={key}
          transform={`translate(${midX}, ${midY}) rotate(${angleDeg})`}
          opacity={opacity}
          pointerEvents="none"
        >
          <path d={arrowPath} fill={color} />
        </g>,
      );
    }

    cachedArrows.current = result;
    return result;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim, venue, nodePositions]);

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
        zIndex: 3,
        overflow: 'visible',
      }}
      aria-hidden="true"
    >
      {arrows}
    </svg>
  );
}

export default FlowArrowLayer;
