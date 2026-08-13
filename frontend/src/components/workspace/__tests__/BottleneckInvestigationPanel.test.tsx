import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ContextPanel from '../ContextPanel';
import type { PanelProps } from '../ContextPanel';
import type { SimulationState, VenueModel } from '../../../lib/types';

// Mock SimulationContext
vi.mock('../../../store/SimulationContext', () => ({
  useSimulation: () => ({
    cfSimId: null,
    aiConfigured: null,
    aiBusy: false,
    aiIdeas: [],
    aiExplanation: null,
    aiError: null,
    explainCurrent: vi.fn(),
  }),
}));

// Mock sub-components to keep tests focused
vi.mock('../WeatherPanel', () => ({ WeatherPanel: () => null }));
vi.mock('../CausalGraphPanel', () => ({ CausalGraphPanel: () => null }));

const makeVenue = (): VenueModel => ({
  id: 'v1', name: 'Test', width: 1000, height: 620, nodes: [], edges: [],
});

const makeSim = (withBottleneck = false): SimulationState => ({
  sim_id: 's1', scenario_id: 'sc1', venue_id: 'v1',
  status: 'RUNNING', t_min: 5, tick: 100, phase: 'PEAK', speed: 10,
  emergency_active: false, interventions_applied: [], simulation_scale: 1, node_positions: {},
  metrics: {
    t_min: 5, in_venue: 500, total_spawned: 500, total_completed: 0,
    global_density: 1.2, flow_per_min: 120, max_utilisation: 0.9, avg_utilisation: 0.6,
    queue_total: 80, queue_growth: 2, avg_travel_time_min: 4, max_travel_time_min: 8,
    bottleneck_count: withBottleneck ? 1 : 0, risk_level: withBottleneck ? 'HIGH' : 'NORMAL',
    risk_score: 0.8, clearance_time_min: null,
    avg_stress: 0.4, avg_fatigue: 0.3, avg_patience: 0.7, avg_hydration: 0.9, water_seekers: 0,
  },
  history: [],
  nodes: {
    'GATE_A': { id: 'GATE_A', type: 'CORRIDOR', people: 10, flow_per_min: 100, capacity: 200, utilisation: 0.5, density: 1.0, risk: 'NORMAL', risk_score: 0.3, queue: 5, trend: 'STABLE' },
  },
  edges: {
    'GATE_A→CONCOURSE_N': { id: 'GATE_A→CONCOURSE_N', type: 'CORRIDOR', people: 80, flow_per_min: 150, capacity: 200, utilisation: 0.75, density: 2.5, risk: withBottleneck ? 'HIGH' : 'NORMAL', risk_score: 0.7, queue: 30, trend: 'RISING', time_to_critical_min: withBottleneck ? 2.5 : null },
  },
  bottlenecks: withBottleneck ? [{
    id: 'b1', kind: 'edge', location: 'GATE_A→CONCOURSE_N',
    current_risk: 'HIGH', current_density: 2.5, capacity_utilisation: 0.75,
    queue: 30, trend: 'RISING', estimated_time_to_critical_min: 2.5,
    explanation: 'High concentration detected',
  }] : [],
  agents: [],
  recommended_action: null,
});

const baseProps: PanelProps = {
  mode: 'investigate',
  sim: null,
  venue: makeVenue(),
  selected: null,
  onSelect: vi.fn(),
  guidedCta: null,
  drafts: null,
  onToggleClose: vi.fn(),
  onImplementClose: vi.fn(),
  onSetRedirect: vi.fn(),
  onImplementRedirect: vi.fn(),
  onEmergency: vi.fn(),
  onIntervention: vi.fn(),
  cfSim: null,
  cfError: null,
  onDiscardCf: vi.fn(),
  onApplyCf: vi.fn(),
  runCounterfactual: vi.fn(),
};

describe('ContextPanel — BottleneckInvestigationPanel mutual exclusivity (Req 9)', () => {
  it('renders BottleneckInvestigationPanel when selected matches a bottleneck (Req 9.1)', () => {
    const sim = makeSim(true);
    render(
      <ContextPanel
        {...baseProps}
        sim={sim}
        selected={{ kind: 'edge', id: 'GATE_A→CONCOURSE_N' }}
      />,
    );
    // BottleneckInvestigationPanel renders "WHAT" block header
    expect(screen.getByText('WHAT')).toBeInTheDocument();
  });

  it('renders ObjectDetail when selected does NOT match a bottleneck (Req 9.2)', () => {
    const sim = makeSim(true); // has bottleneck at GATE_A→CONCOURSE_N
    render(
      <ContextPanel
        {...baseProps}
        sim={sim}
        selected={{ kind: 'node', id: 'GATE_A' }} // different element — not a bottleneck
      />,
    );
    // ObjectDetail renders "Selected" section
    expect(screen.getByText('Selected')).toBeInTheDocument();
    // BottleneckInvestigationPanel should NOT be rendered
    expect(screen.queryByText('WHAT')).not.toBeInTheDocument();
  });
});
