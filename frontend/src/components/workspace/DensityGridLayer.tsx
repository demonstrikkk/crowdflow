import { useEffect, useRef } from 'react';
import type { AgentModel, VenueModel } from '../../lib/types';

/**
 * DensityGridLayer — 20×20 spatial bin heatmap rendered on a Canvas 2D element.
 *
 * Requirements: Req 3, Req 17
 * - Only visible when viewMode === 'density' or viewMode === 'crowd' (Req 3.1)
 * - Accumulates scale_units (not agent count) per bin (Req 3.2)
 * - Updates via useEffect watching sim.agents — NOT a rAF loop (Req 3.3)
 * - Skips cells with value < 0.5 (Req 3.5)
 * - Colors: hsla(hue, 75%, 48%, alpha) where hue = 120 − (val/max)*120 (Req 3.6)
 * - Must complete in < 2ms for 1,200 agents (Req 3.7 / Req 17.2)
 */

const GRID_W = 20;
const GRID_H = 20;

function computeDensityGrid(
  agents: AgentModel[],
  venueW: number,
  venueH: number,
): Float32Array {
  const grid = new Float32Array(GRID_W * GRID_H);
  const cellW = venueW / GRID_W;
  const cellH = venueH / GRID_H;
  for (const a of agents) {
    const col = Math.min(GRID_W - 1, Math.floor(a.position.x / cellW));
    const row = Math.min(GRID_H - 1, Math.floor(a.position.y / cellH));
    grid[row * GRID_W + col] += a.scale_units;
  }
  return grid;
}

interface DensityGridLayerProps {
  agents: AgentModel[] | null;
  venue: VenueModel;
  visible: boolean; // true when viewMode === 'density' || 'crowd'
}

export function DensityGridLayer({ agents, venue, visible }: DensityGridLayerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const W = venue.width;
  const H = venue.height;
  const cellW = W / GRID_W;
  const cellH = H / GRID_H;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !visible || !agents || agents.length === 0) {
      // Clear canvas when not visible or no agents
      const ctx = canvas?.getContext('2d');
      if (ctx) ctx.clearRect(0, 0, canvas!.width, canvas!.height);
      return;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const cw = canvas.width;
    const ch = canvas.height;

    const scaleX = cw / W;
    const scaleY = ch / H;
    const pxCellW = cellW * scaleX;
    const pxCellH = cellH * scaleY;

    // Compute grid (Req 3.2)
    const grid = computeDensityGrid(agents, W, H);

    // Find max for normalisation
    let maxVal = 0;
    for (let i = 0; i < grid.length; i++) {
      if (grid[i] > maxVal) maxVal = grid[i];
    }

    ctx.clearRect(0, 0, cw, ch);

    if (maxVal === 0) return;

    // Draw cells (Req 3.5 / Req 3.6)
    for (let row = 0; row < GRID_H; row++) {
      for (let col = 0; col < GRID_W; col++) {
        const val = grid[row * GRID_W + col];
        if (val < 0.5) continue; // skip near-empty cells (Req 3.5)

        const ratio = val / maxVal;
        const hue = 120 - ratio * 120;              // green → red
        const alpha = 0.06 + ratio * 0.38;          // Req 3.6
        ctx.fillStyle = `hsla(${hue}, 75%, 48%, ${alpha})`;
        ctx.fillRect(col * pxCellW, row * pxCellH, pxCellW, pxCellH);
      }
    }
  }, [agents, visible, W, H, cellW, cellH]);

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
        pointerEvents: 'none',
        zIndex: 1,
        display: visible ? 'block' : 'none',
      }}
      aria-hidden="true"
    />
  );
}

export default DensityGridLayer;
