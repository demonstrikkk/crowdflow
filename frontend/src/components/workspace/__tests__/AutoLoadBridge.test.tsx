import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { AutoLoadBridge } from '../AutoLoadBridge';

// Mock useSimulation
const mockSelectVenue = vi.fn();
const mockSelectScenario = vi.fn().mockResolvedValue(undefined);

const baseContext = {
  venues: [],
  venue: null,
  scenarios: [],
  selectVenue: mockSelectVenue,
  selectScenario: mockSelectScenario,
};

vi.mock('../../../store/SimulationContext', () => ({
  useSimulation: () => mockContext,
}));

let mockContext = { ...baseContext };

beforeEach(() => {
  vi.clearAllMocks();
  mockContext = { ...baseContext };
});

const unityArenaVenue = { id: 'unity_arena', name: 'Unity Arena', width: 1000, height: 620, nodes: [], edges: [] };
const otherVenue = { id: 'other_venue', name: 'Other', width: 800, height: 600, nodes: [], edges: [] };

const defaultScenario = {
  id: 'sc1', name: 'Default Scenario', venue_id: 'unity_arena',
  crowd_size: 1000, arrival_rate_per_minute: 50, exit_rate_per_minute: 30,
  surge_departure_spread_min: 10, gate_distribution: {}, destination_distribution: {},
  exit_distribution: {}, event_phases: [], special: { default: true },
};

const otherScenario = {
  ...defaultScenario, id: 'sc2', name: 'Other Scenario', special: {},
};

describe('AutoLoadBridge', () => {
  it('calls selectVenue once when venues are available and venue is null', () => {
    mockContext = { ...baseContext, venues: [unityArenaVenue], venue: null, scenarios: [] };
    render(<AutoLoadBridge />);
    expect(mockSelectVenue).toHaveBeenCalledTimes(1);
  });

  it('prefers unity_arena over other venues', () => {
    mockContext = { ...baseContext, venues: [otherVenue, unityArenaVenue], venue: null, scenarios: [] };
    render(<AutoLoadBridge />);
    expect(mockSelectVenue).toHaveBeenCalledWith('unity_arena');
  });

  it('falls back to venues[0] when unity_arena is not present', () => {
    mockContext = { ...baseContext, venues: [otherVenue], venue: null, scenarios: [] };
    render(<AutoLoadBridge />);
    expect(mockSelectVenue).toHaveBeenCalledWith('other_venue');
  });

  it('does not call selectVenue when venues.length === 0', () => {
    mockContext = { ...baseContext, venues: [], venue: null, scenarios: [] };
    render(<AutoLoadBridge />);
    expect(mockSelectVenue).not.toHaveBeenCalled();
  });

  it('does not call selectVenue when venue is already set', () => {
    mockContext = { ...baseContext, venues: [unityArenaVenue], venue: unityArenaVenue, scenarios: [] };
    render(<AutoLoadBridge />);
    expect(mockSelectVenue).not.toHaveBeenCalled();
  });

  it('calls selectScenario for the default scenario', () => {
    mockContext = {
      ...baseContext,
      venues: [unityArenaVenue],
      venue: null,
      scenarios: [otherScenario, defaultScenario],
    };
    render(<AutoLoadBridge />);
    expect(mockSelectScenario).toHaveBeenCalledWith('sc1');
  });

  it('is idempotent — selectVenue called at most once even if effect re-runs', () => {
    mockContext = { ...baseContext, venues: [unityArenaVenue], venue: null, scenarios: [] };
    const { rerender } = render(<AutoLoadBridge />);
    rerender(<AutoLoadBridge />);
    rerender(<AutoLoadBridge />);
    expect(mockSelectVenue).toHaveBeenCalledTimes(1);
  });
});
