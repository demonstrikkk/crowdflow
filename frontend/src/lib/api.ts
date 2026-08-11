import type {
  AiExplainResponse,
  AiInterpretResponse,
  AiProviderStatus,
  AiSuggestResponse,
  BlueprintResult,
  Bottleneck,
  ExternalEnvironment,
  Intervention,
  OptimizationResult,
  ScenarioDelta,
  ScenarioModel,
  SimulationState,
  VenueModel,
} from './types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(String(detail));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  venue: (id: string) => request<VenueModel>(`/venues/${id}`),
  listVenues: () => request<VenueModel[]>('/venues'),
  createVenue: (venue: VenueModel) =>
    request<VenueModel>('/venues', { method: 'POST', body: JSON.stringify(venue) }),
  saveVenue: (venue: VenueModel) =>
    request<VenueModel>(`/venues/${venue.id}`, { method: 'PUT', body: JSON.stringify(venue) }),
  deleteVenue: (id: string) => request<void>(`/venues/${id}`, { method: 'DELETE' }),
  importBlueprint: (file: File) => {
    const form = new FormData();
    form.append('file', file, file.name);
    return fetch(`${API_BASE}/blueprint/import`, { method: 'POST', body: form }).then(
      async (res) => {
        if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText);
        return (await res.json()) as BlueprintResult;
      },
    );
  },

  listScenarios: () => request<ScenarioModel[]>('/scenarios'),
  scenario: (id: string) => request<ScenarioModel>(`/scenarios/${id}`),
  createScenario: (scenario: ScenarioModel) =>
    request<ScenarioModel>('/scenarios', { method: 'POST', body: JSON.stringify(scenario) }),
  saveScenario: (scenario: ScenarioModel) =>
    request<ScenarioModel>(`/scenarios/${scenario.id}`, {
      method: 'PUT',
      body: JSON.stringify(scenario),
    }),
  deleteScenario: (id: string) => request<void>(`/scenarios/${id}`, { method: 'DELETE' }),

  runSimulation: (scenarioId: string) =>
    request<SimulationState>('/simulation/run', {
      method: 'POST',
      body: JSON.stringify({ scenario_id: scenarioId }),
    }),
  simulationState: (simId: string) => request<SimulationState>(`/simulation/${simId}`),
  bottlenecks: (simId: string) => request<Bottleneck[]>(`/simulation/${simId}/bottlenecks`),
  stepSimulation: (simId: string, steps = 1) =>
    request<SimulationState>(`/simulation/${simId}/step`, {
      method: 'POST',
      body: JSON.stringify({ steps }),
    }),
  playSimulation: (simId: string) =>
    request<{ status: string }>(`/simulation/${simId}/play`, { method: 'POST' }),
  pauseSimulation: (simId: string) =>
    request<{ status: string }>(`/simulation/${simId}/pause`, { method: 'POST' }),
  resetSimulation: (simId: string) =>
    request<SimulationState>(`/simulation/${simId}/reset`, { method: 'POST' }),
  setSpeed: (simId: string, speed: number) =>
    request<{ speed: number }>(`/simulation/${simId}/speed`, {
      method: 'POST',
      body: JSON.stringify({ speed }),
    }),
  emergency: (simId: string, active: boolean) =>
    request<SimulationState>(`/simulation/${simId}/emergency`, {
      method: 'POST',
      body: JSON.stringify({ active }),
    }),
  optimize: (simId: string) =>
    request<OptimizationResult>(`/simulation/${simId}/optimize`, { method: 'POST' }),
  applyIntervention: (simId: string, intervention: Intervention) =>
    request<SimulationState>(`/simulation/${simId}/apply`, {
      method: 'POST',
      body: JSON.stringify(intervention),
    }),
  counterfactual: (simId: string, intervention: Intervention) =>
    request<SimulationState>(`/simulation/${simId}/counterfactual`, {
      method: 'POST',
      body: JSON.stringify(intervention),
    }),
  recommendRoute: (simId: string, source: string, destination: string) =>
    request<{ path: string[] }>(`/simulation/${simId}/recommend-route`, {
      method: 'POST',
      body: JSON.stringify({ sim_id: simId, source, destination }),
    }),
  emergencyRoute: (simId: string, nodeId: string) =>
    request<{ path: string[]; emergency_exit: string }>(`/simulation/${simId}/emergency-route`, {
      method: 'POST',
      body: JSON.stringify({ sim_id: simId, node_id: nodeId }),
    }),

  aiStatus: () => request<AiProviderStatus>('/ai/status'),
  aiInterpret: (query: string, scenarioId: string) =>
    request<AiInterpretResponse>('/ai/interpret', {
      method: 'POST',
      body: JSON.stringify({ query, scenario_id: scenarioId }),
    }),
  aiSimulate: (query: string, scenarioId: string) =>
    request<SimulationState>('/ai/simulate', {
      method: 'POST',
      body: JSON.stringify({ query, scenario_id: scenarioId }),
    }),
  aiSimulateDelta: (scenarioId: string, delta: ScenarioDelta) =>
    request<SimulationState>('/ai/simulate', {
      method: 'POST',
      body: JSON.stringify({ scenario_id: scenarioId, delta }),
    }),
  aiExplain: (simId: string) =>
    request<AiExplainResponse>('/ai/explain', {
      method: 'POST',
      body: JSON.stringify({ sim_id: simId }),
    }),
  aiSuggest: (scenarioId: string) =>
    request<AiSuggestResponse>('/ai/suggest', {
      method: 'POST',
      body: JSON.stringify({ scenario_id: scenarioId }),
    }),

  environment: (venueId: string) =>
    request<ExternalEnvironment>(`/environment?venue_id=${encodeURIComponent(venueId)}`),
  refreshEnvironment: (venueId: string) =>
    request<ExternalEnvironment>(`/environment/refresh?venue_id=${encodeURIComponent(venueId)}`, {
      method: 'POST',
    }),

  health: () => request<{ status: string; venues_loaded?: number; scenarios_loaded?: number }>('/health'),
};

export function wsUrl(simId: string): string {
  const base = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api';
  const wsBase = base.replace(/^http/, 'ws');
  return `${wsBase}/simulation/${simId}/live`;
}

export { API_BASE };