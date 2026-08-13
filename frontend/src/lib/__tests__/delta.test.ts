import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { computeDelta, deltaColor } from '../delta';
import type { SimulationState } from '../types';

// Minimal SimulationState stub
function makeState(edges: Record<string, unknown> = {}, nodes: Record<string, unknown> = {}): SimulationState {
  return {
    sim_id: 'test',
    scenario_id: 's1',
    venue_id: 'v1',
    status: 'RUNNING',
    t_min: 0,
    tick: 0,
    phase: 'ENTRY',
    speed: 10,
    emergency_active: false,
    interventions_applied: [],
    metrics: {
      t_min: 0, in_venue: 0, total_spawned: 0, total_completed: 0,
      global_density: 0, flow_per_min: 0, max_utilisation: 0, avg_utilisation: 0,
      queue_total: 0, queue_growth: 0, avg_travel_time_min: 0, max_travel_time_min: 0,
      bottleneck_count: 0, risk_level: 'NORMAL', risk_score: 0, clearance_time_min: null,
      avg_stress: 0, avg_fatigue: 0, avg_patience: 0, avg_hydration: 0, water_seekers: 0,
    },
    history: [],
    nodes: nodes as SimulationState['nodes'],
    edges: edges as SimulationState['edges'],
    bottlenecks: [],
    agents: [],
    simulation_scale: 1,
    node_positions: {},
  };
}

function makeElementState(density: number, flowPerMin: number, utilisation = 0) {
  return {
    id: 'e1', type: 'CORRIDOR', people: 0,
    flow_per_min: flowPerMin, capacity: 200, utilisation,
    density, risk: 'NORMAL' as const, risk_score: 0, queue: 0, trend: 'STABLE',
  };
}

describe('computeDelta', () => {
  it('computes correct densityDelta and flowDelta for known fixtures', () => {
    const baseEdge = makeElementState(2.0, 100);
    const cfEdge = makeElementState(1.2, 80);

    const base = makeState({ 'GATE_A→CONCOURSE_N': baseEdge });
    const cf = makeState({ 'GATE_A→CONCOURSE_N': cfEdge });

    const result = computeDelta(base, cf);
    expect(result).toHaveLength(1);
    expect(result[0].densityDelta).toBeCloseTo(1.2 - 2.0);    // -0.8
    expect(result[0].flowDelta).toBeCloseTo(80 - 100);          // -20
    expect(result[0].kind).toBe('edge');
    expect(result[0].id).toBe('GATE_A→CONCOURSE_N');
  });

  it('skips keys absent from one state', () => {
    const base = makeState({ 'A→B': makeElementState(1, 10), 'C→D': makeElementState(2, 20) });
    const cf = makeState({ 'A→B': makeElementState(1.5, 15) }); // 'C→D' missing from cf

    const result = computeDelta(base, cf);
    // Only 'A→B' should be in result — 'C→D' absent from cf is skipped
    expect(result.every((d) => d.id !== 'C→D')).toBe(true);
    expect(result.some((d) => d.id === 'A→B')).toBe(true);
  });

  it('satisfies anti-symmetry: densityDelta(base,cf) === -densityDelta(cf,base)', () => {
    const e1 = makeElementState(3.0, 150, 0.75);
    const e2 = makeElementState(1.5, 90, 0.45);

    const base = makeState({ 'X→Y': e1 });
    const cf = makeState({ 'X→Y': e2 });

    const forward = computeDelta(base, cf);
    const backward = computeDelta(cf, base);

    expect(forward).toHaveLength(1);
    expect(backward).toHaveLength(1);
    expect(forward[0].densityDelta).toBeCloseTo(-backward[0].densityDelta, 10);
    expect(forward[0].flowDelta).toBeCloseTo(-backward[0].flowDelta, 10);
    expect(forward[0].utilDelta).toBeCloseTo(-backward[0].utilDelta, 10);
  });
});

describe('deltaColor property test', () => {
  it('always returns a non-empty string for any float inputs', () => {
    fc.assert(
      fc.property(
        fc.float({ min: -1, max: 1, noNaN: true }),
        fc.float({ min: -200, max: 200, noNaN: true }),
        (densityDelta, flowDelta) => {
          const color = deltaColor(densityDelta, flowDelta);
          return typeof color === 'string' && color.length > 0;
        },
      ),
      { numRuns: 500 },
    );
  });
});
