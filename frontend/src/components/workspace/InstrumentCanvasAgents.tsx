import { useEffect, useRef } from 'react';
import type { VenueModel, SimulationState } from '../../lib/types';

/**
 * Canvas2DAgentLayer — renders crowd agents using a requestAnimationFrame loop.
 *
 * Key design decisions (Req 1, Req 2, Req 17, Req 19):
 * - Reads from simRef (a ref, not state) so zero React renders per frame
 * - Pre-allocates Float32Array buffers — no GC pressure per frame
 * - pointer-events: none so SVG hit-testing is unaffected
 * - Falls back gracefully when 2D context is unavailable (Req 19)
 */

interface AgentLayerProps {
  simRef: React.RefObject<SimulationState | null>;
  venue: VenueModel;
  showAgents: boolean;
  viewBoxX: number;
  viewBoxY: number;
  viewBoxW: number;
  viewBoxH: number;
  /** Called once if Canvas 2D is unavailable, allowing parent to show SVG fallback */
  onCanvasUnsupported?: () => void;
}

// Pre-allocated position buffers: [x0, y0, x1, y1, ...] interleaved
// normal: 4000 agents max * 2 floats, rerouted: 400 * 2, emergency: 200 * 2
const NORMAL_BUF = new Float32Array(4000 * 2);
const REROUTED_BUF = new Float32Array(400 * 2);
const EMERGENCY_BUF = new Float32Array(200 * 2);

export function InstrumentCanvasAgents({
  simRef,
  venue,
  showAgents,
  viewBoxX,
  viewBoxY,
  viewBoxW,
  viewBoxH,
  onCanvasUnsupported,
}: AgentLayerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number>(0);

  const W = venue.width;
  const H = venue.height;
  const m = Math.min(W, H);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      // Canvas 2D unavailable — signal parent and abort (Req 19.1)
      console.warn('[InstrumentCanvasAgents] Canvas 2D context unavailable — falling back to SVG agents');
      onCanvasUnsupported?.();
      return;
    }

    let disposed = false;

    function draw() {
      if (disposed) return;
      rafRef.current = requestAnimationFrame(draw);

      const canvas2 = canvasRef.current;
      if (!canvas2 || !ctx) return;

      const cw = canvas2.width;
      const ch = canvas2.height;

      // Always clear before any condition check
      ctx.clearRect(0, 0, cw, ch);

      // Skip drawing when hidden (Req 2.5)
      if (!showAgents) return;

      const state = simRef.current;
      if (!state || state.agents.length === 0) return;

      // Coordinate transform (Req 2.6)
      const scaleX = cw / viewBoxW;
      const scaleY = ch / viewBoxH;
      const agentRadius = Math.max(1.5, (cw / viewBoxW) * (m / 46) * 0.2);

      let ni = 0; // normal index
      let ri = 0; // rerouted index
      let ei = 0; // emergency index

      for (const a of state.agents) {
        const cx = (a.position.x - viewBoxX) * scaleX;
        const cy = (a.position.y - viewBoxY) * scaleY;
        if (a.is_emergency) {
          if (ei < EMERGENCY_BUF.length - 1) { EMERGENCY_BUF[ei++] = cx; EMERGENCY_BUF[ei++] = cy; }
        } else if (a.is_rerouted) {
          if (ri < REROUTED_BUF.length - 1) { REROUTED_BUF[ri++] = cx; REROUTED_BUF[ri++] = cy; }
        } else {
          if (ni < NORMAL_BUF.length - 1) { NORMAL_BUF[ni++] = cx; NORMAL_BUF[ni++] = cy; }
        }
      }

      // Batch-draw each category (Req 2.3) — one beginPath/fill per category
      const drawCategory = (buf: Float32Array, count: number, color: string) => {
        if (count === 0) return;
        ctx!.beginPath();
        for (let i = 0; i < count; i += 2) {
          ctx!.moveTo(buf[i] + agentRadius, buf[i + 1]);
          ctx!.arc(buf[i], buf[i + 1], agentRadius, 0, Math.PI * 2);
        }
        ctx!.fillStyle = color;
        ctx!.globalAlpha = 0.75;
        ctx!.fill();
        ctx!.globalAlpha = 1;
      };

      drawCategory(NORMAL_BUF, ni, '#c8cdd6');         // var(--od-ink) approximate
      drawCategory(REROUTED_BUF, ri, '#f59e0b');       // var(--od-warn) approximate
      drawCategory(EMERGENCY_BUF, ei, '#ef4444');      // var(--od-emergency) approximate
    }

    rafRef.current = requestAnimationFrame(draw);

    return () => {
      disposed = true;
      cancelAnimationFrame(rafRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [simRef, showAgents, viewBoxX, viewBoxY, viewBoxW, viewBoxH, m, onCanvasUnsupported]);

  return (
    <canvas
      ref={canvasRef}
      width={800}
      height={600}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',  // Req 1.6 / Req 2
        zIndex: 2,
      }}
      aria-hidden="true"
    />
  );
}

export default InstrumentCanvasAgents;
