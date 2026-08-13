import type { SimulationState } from './types';

/**
 * Describes the signed difference in density, flow, utilisation, and risk
 * between a baseline and a counterfactual simulation state for a single
 * edge or node.
 *
 * Defined here (not in lib/types.ts) per Req 21.
 */
export interface DeltaEntry {
  /** The edge or node key (e.g. "GATE_A→CONCOURSE_N" or a node id) */
  id: string;
  /** Whether this entry refers to an edge or a node */
  kind: 'edge' | 'node';
  /**
   * Signed density difference: cfSim.density - baseSim.density.
   * Negative = improvement (density fell in the CF), positive = worsening.
   */
  densityDelta: number;
  /**
   * Signed flow-per-minute difference: cfSim.flow_per_min - baseSim.flow_per_min.
   */
  flowDelta: number;
  /**
   * Signed utilisation difference: cfSim.utilisation - baseSim.utilisation.
   */
  utilDelta: number;
  /**
   * True when the risk level changed between base and cf.
   */
  riskChanged: boolean;
}

/**
 * Compute the spatial delta between two simulation states.
 *
 * Only keys present in BOTH states are included (Req 8.2).
 * For each included key: delta = cfValue - baseValue (Req 8.3 anti-symmetry).
 *
 * Iterates edges first, then nodes (per task spec).
 *
 * @param base  The baseline SimulationState
 * @param cf    The counterfactual SimulationState
 * @returns     Array of DeltaEntry, one per shared edge or node key
 */
export function computeDelta(
  base: SimulationState,
  cf: SimulationState,
): DeltaEntry[] {
  const result: DeltaEntry[] = [];

  // --- Edges ---
  for (const id of Object.keys(base.edges)) {
    const baseEdge = base.edges[id];
    const cfEdge = cf.edges[id];
    // Skip keys absent from either state (Req 8.2)
    if (cfEdge === undefined) continue;

    result.push({
      id,
      kind: 'edge',
      densityDelta: cfEdge.density - baseEdge.density,
      flowDelta: cfEdge.flow_per_min - baseEdge.flow_per_min,
      utilDelta: cfEdge.utilisation - baseEdge.utilisation,
      riskChanged: cfEdge.risk !== baseEdge.risk,
    });
  }

  // --- Nodes ---
  for (const id of Object.keys(base.nodes)) {
    const baseNode = base.nodes[id];
    const cfNode = cf.nodes[id];
    if (cfNode === undefined) continue;

    result.push({
      id,
      kind: 'node',
      densityDelta: cfNode.density - baseNode.density,
      flowDelta: cfNode.flow_per_min - baseNode.flow_per_min,
      utilDelta: cfNode.utilisation - baseNode.utilisation,
      riskChanged: cfNode.risk !== baseNode.risk,
    });
  }

  return result;
}

/**
 * Map density and flow deltas to a CSS color string for the delta canvas.
 *
 * Rules (Req 7.6 / design §4.2):
 *  - densityDelta < -0.05  → green  (improvement)
 *  - densityDelta > +0.05  → red    (worsening)
 *  - |flowDelta| > 10      → blue   (flow redistributed)
 *  - otherwise             → var(--od-line)
 *
 * Always returns a non-empty string for any finite numeric input (Req 21.5).
 */
export function deltaColor(densityDelta: number, flowDelta: number): string {
  if (densityDelta < -0.05) {
    // Improvement: green — intensity proportional to magnitude
    const intensity = Math.min(1, Math.abs(densityDelta) / 0.3);
    return `hsl(142, 70%, ${45 + intensity * 10}%)`;
  }
  if (densityDelta > 0.05) {
    // Worsening: red — intensity proportional to magnitude
    const intensity = Math.min(1, densityDelta / 0.3);
    return `hsl(0, 70%, ${50 + intensity * 10}%)`;
  }
  if (Math.abs(flowDelta) > 10) {
    // Flow redistributed: blue
    return 'hsl(210, 70%, 55%)';
  }
  // Neutral / below threshold
  return 'var(--od-line)';
}
