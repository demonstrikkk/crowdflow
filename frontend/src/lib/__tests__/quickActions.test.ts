import { describe, it, expect } from 'vitest';
import { quickActionsFor } from '../quickActions';
import type { Bottleneck, SimulationState, VenueModel } from '../types';

function makeBottleneck(location: string): Bottleneck {
  return {
    id: 'b1',
    kind: 'edge',
    location,
    current_risk: 'HIGH',
    current_density: 3.0,
    capacity_utilisation: 0.85,
    queue: 40,
    trend: 'RISING',
    estimated_time_to_critical_min: 2.0,
    explanation: 'High concentration',
  };
}

function makeVenue(edges: VenueModel['edges'] = []): VenueModel {
  return {
    id: 'v1',
    name: 'Test Venue',
    width: 1000,
    height: 620,
    nodes: [],
    edges,
  };
}

function makeSim(): SimulationState {
  return {
    sim_id: 'test',
    scenario_id: 's1',
    venue_id: 'v1',
    status: 'RUNNING',
    t_min: 5,
    tick: 100,
    phase: 'PEAK',
    speed: 10,
    emergency_active: false,
    interventions_applied: [],
    metrics: {
      t_min: 5, in_venue: 500, total_spawned: 500, total_completed: 0,
      global_density: 1.2, flow_per_min: 120, max_utilisation: 0.9, avg_utilisation: 0.6,
      queue_total: 80, queue_growth: 2, avg_travel_time_min: 4, max_travel_time_min: 8,
      bottleneck_count: 1, risk_level: 'HIGH', risk_score: 0.8, clearance_time_min: null,
      avg_stress: 0.4, avg_fatigue: 0.3, avg_patience: 0.7, avg_hydration: 0.9, water_seekers: 5,
    },
    history: [],
    nodes: {},
    edges: {},
    bottlenecks: [],
    agents: [],
    simulation_scale: 1,
    node_positions: {},
  };
}

describe('quickActionsFor', () => {
  it('always returns at least one action', () => {
    const b = makeBottleneck('GATE_A→CONCOURSE_N');
    const venue = makeVenue([]);
    const sim = makeSim();
    const actions = quickActionsFor(b, venue, sim);
    expect(actions.length).toBeGreaterThanOrEqual(1);
  });

  it('always includes CLOSE_CORRIDOR as fallback', () => {
    const b = makeBottleneck('GATE_A→CONCOURSE_N');
    const venue = makeVenue([]);
    const sim = makeSim();
    const actions = quickActionsFor(b, venue, sim);
    const closeAction = actions.find((a) => a.intervention.type === 'CLOSE_CORRIDOR');
    expect(closeAction).toBeDefined();
  });

  it('CLOSE_CORRIDOR variant is warn', () => {
    const b = makeBottleneck('GATE_A→CONCOURSE_N');
    const venue = makeVenue([]);
    const sim = makeSim();
    const actions = quickActionsFor(b, venue, sim);
    const closeAction = actions.find((a) => a.intervention.type === 'CLOSE_CORRIDOR');
    expect(closeAction?.variant).toBe('warn');
  });

  it('includes REDIRECT actions when alternate open edges exist', () => {
    const b = makeBottleneck('GATE_A→CONCOURSE_N');
    const venue = makeVenue([
      // The bottleneck edge itself
      { id: 'GATE_A→CONCOURSE_N', source: 'GATE_A', destination: 'CONCOURSE_N', length_m: 50, width_m: 10, capacity: 200, is_open: true, is_emergency: false },
      // Alternate open edge from same source
      { id: 'GATE_A→CONCOURSE_W', source: 'GATE_A', destination: 'CONCOURSE_W', length_m: 60, width_m: 10, capacity: 180, is_open: true, is_emergency: false },
    ]);
    const sim = makeSim();
    const actions = quickActionsFor(b, venue, sim);
    const redirectActions = actions.filter((a) => a.intervention.type === 'REDIRECT');
    expect(redirectActions.length).toBeGreaterThanOrEqual(1);
  });

  it('REDIRECT variant is ok', () => {
    const b = makeBottleneck('GATE_A→CONCOURSE_N');
    const venue = makeVenue([
      { id: 'GATE_A→CONCOURSE_N', source: 'GATE_A', destination: 'CONCOURSE_N', length_m: 50, width_m: 10, capacity: 200, is_open: true, is_emergency: false },
      { id: 'GATE_A→CONCOURSE_W', source: 'GATE_A', destination: 'CONCOURSE_W', length_m: 60, width_m: 10, capacity: 180, is_open: true, is_emergency: false },
    ]);
    const sim = makeSim();
    const actions = quickActionsFor(b, venue, sim);
    const redirectActions = actions.filter((a) => a.intervention.type === 'REDIRECT');
    redirectActions.forEach((a) => expect(a.variant).toBe('ok'));
  });

  it('does not add REDIRECT for closed alternate edges', () => {
    const b = makeBottleneck('GATE_A→CONCOURSE_N');
    const venue = makeVenue([
      { id: 'GATE_A→CONCOURSE_N', source: 'GATE_A', destination: 'CONCOURSE_N', length_m: 50, width_m: 10, capacity: 200, is_open: true, is_emergency: false },
      // This alternate is CLOSED — should not appear as REDIRECT
      { id: 'GATE_A→CONCOURSE_W', source: 'GATE_A', destination: 'CONCOURSE_W', length_m: 60, width_m: 10, capacity: 180, is_open: false, is_emergency: false },
    ]);
    const sim = makeSim();
    const actions = quickActionsFor(b, venue, sim);
    const redirectActions = actions.filter((a) => a.intervention.type === 'REDIRECT');
    expect(redirectActions).toHaveLength(0);
  });
});
