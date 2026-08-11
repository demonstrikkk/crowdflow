export type NodeType =
  | 'ENTRY'
  | 'EXIT'
  | 'EMERGENCY_EXIT'
  | 'INTERSECTION'
  | 'CONCESSION'
  | 'CHECKPOINT'
  | 'ZONE';

export type RiskLevel = 'NORMAL' | 'ELEVATED' | 'HIGH' | 'CRITICAL';
export type ScenarioPhase = 'NORMAL' | 'GATE_OVERLOAD' | 'POST_EVENT_EXIT_SURGE';
export type EventPhaseName = 'ENTRY' | 'PEAK' | 'INTERVAL' | 'EXIT_SURGE';
export type SimulationStatus = 'IDLE' | 'RUNNING' | 'PAUSED' | 'COMPLETED';
export type InterventionType =
  | 'REDIRECT'
  | 'CHANGE_GATE'
  | 'OPEN_CORRIDOR'
  | 'CLOSE_CORRIDOR'
  | 'USE_ALTERNATE_EXIT'
  | 'ADJUST_ROUTING'
  | 'EMERGENCY_RESPONSE'
  | 'INCREASE_CAPACITY'
  | 'ADD_INCIDENT'
  | 'SET_WEATHER';

export type IncidentType = 'FIRE' | 'SECURITY' | 'STRUCTURAL';
export type WeatherCondition = 'HEAVY_RAIN' | 'HAIL' | 'HEAT' | 'FOG' | 'CLEAR';

export interface Position {
  x: number;
  y: number;
}

export interface NodeModel {
  id: string;
  position: Position;
  type: NodeType;
  capacity?: number | null;
  area_m2?: number | null;
  metadata: Record<string, unknown>;
}

export interface EdgeModel {
  id: string;
  source: string;
  destination: string;
  length_m: number;
  width_m: number;
  capacity: number;
  is_open: boolean;
  is_emergency: boolean;
  exposure?: 'INDOOR' | 'OUTDOOR';
}

export interface VenueModel {
  id: string;
  name: string;
  width: number;
  height: number;
  nodes: NodeModel[];
  edges: EdgeModel[];
}

export interface BlueprintElement {
  id: string;
  kind: NodeType | 'INTERSECTION';
  position: Position;
  area_m2?: number | null;
  confidence: number;
  label?: string | null;
  source: 'GEOMETRY' | 'OCR' | 'CLASSIFIER' | 'TEMPLATE';
}

export interface BlueprintResult {
  venue: VenueModel;
  elements: BlueprintElement[];
  confidence: number;
  degradation_level: number;
  degraded: boolean;
  steps: Record<string, string>;
  notes: string[];
}

export interface EventPhaseModel {
  name: EventPhaseName;
  start_minute: number;
  end_minute: number;
  arrival_rate_multiplier: number;
  spawn?: string | null;
}

export interface ScenarioModel {
  id: string;
  name: string;
  venue_id: string;
  crowd_size: number;
  arrival_rate_per_minute: number;
  exit_rate_per_minute: number;
  surge_departure_spread_min: number;
  gate_distribution: Record<string, number>;
  destination_distribution: Record<string, number>;
  exit_distribution: Record<string, number>;
  event_phases: EventPhaseModel[];
  special: Record<string, unknown>;
}

export interface AgentModel {
  id: number;
  position: Position;
  destination: string;
  route: string[];
  speed_mps: number;
  scale_units: number;
  is_rerouted: boolean;
  is_emergency: boolean;
}

export interface ElementState {
  id: string;
  type: string;
  people: number;
  flow_per_min: number;
  capacity: number;
  utilisation: number;
  density: number;
  risk: RiskLevel;
  risk_score: number;
  queue: number;
  trend: string;
  time_to_critical_min?: number | null;
  hazard?: boolean;
}

export interface IncidentModel {
  type: IncidentType;
  location: string;
  radius_m: number;
  spread_rate_m_min: number;
  severity?: string;
  blocks_exits?: string[];
}

export interface WeatherModel {
  condition: WeatherCondition;
  capacity_multiplier: number;
  speed_multiplier: number;
  unsafe_outdoor: boolean;
  applies_outdoor_only?: boolean;
}

export interface HazardZone {
  location: string | null;
  radius_m: number;
  nodes: string[];
  edges: string[];
}

export interface SimulationMetrics {
  t_min: number;
  in_venue: number;
  total_spawned: number;
  total_completed: number;
  global_density: number;
  flow_per_min: number;
  max_utilisation: number;
  avg_utilisation: number;
  queue_total: number;
  queue_growth: number;
  avg_travel_time_min: number;
  max_travel_time_min: number;
  bottleneck_count: number;
  risk_level: RiskLevel;
  risk_score: number;
  clearance_time_min?: number | null;
}

export interface Bottleneck {
  id: string;
  kind: 'edge' | 'node';
  location: string;
  current_risk: RiskLevel;
  current_density: number;
  capacity_utilisation: number;
  queue: number;
  trend: string;
  estimated_time_to_critical_min?: number | null;
  explanation: string;
}

export interface Intervention {
  id: string;
  type: InterventionType;
  description: string;
  parameters: Record<string, unknown>;
}

export interface OptimizationCandidate {
  intervention: Intervention;
  score: number;
  improvement: Record<string, number>;
  baseline_metrics: SimulationMetrics;
  candidate_metrics: SimulationMetrics;
  baseline_bottlenecks: Bottleneck[];
  candidate_bottlenecks: Bottleneck[];
}

export interface OptimizationResult {
  baseline_metrics: SimulationMetrics;
  candidates: OptimizationCandidate[];
}

export interface CrowdEstimate {
  model_id: string;
  estimated_count: number;
  detections: Record<string, unknown>[];
  density_score: number;
  mean_confidence: number;
  frame_area_m2?: number | null;
}

export interface SimulationState {
  sim_id: string;
  scenario_id: string;
  venue_id: string;
  status: SimulationStatus;
  t_min: number;
  tick: number;
  phase: string;
  speed: number;
  emergency_active: boolean;
  interventions_applied: Intervention[];
  metrics: SimulationMetrics;
  history: Record<string, unknown>[];
  nodes: Record<string, ElementState>;
  edges: Record<string, ElementState>;
  bottlenecks: Bottleneck[];
  agents: AgentModel[];
  recommended_action?: string | null;
  simulation_scale: number;
  node_positions: Record<string, Position>;
  incident?: IncidentModel | null;
  weather?: WeatherModel | null;
  hazard_zones?: HazardZone[];
  external?: ExternalState | null;
}

// --------------------------------------------------------------------------- //
//  External environment / road network (backend /api/environment + sim.external)
// --------------------------------------------------------------------------- //
export interface WorldPosition {
  x: number;
  y: number;
}

export interface RoadSegmentModel {
  id: string;
  name?: string | null;
  kind: 'ARTERIAL' | 'MAJOR' | 'LOCAL' | 'ACCESS' | 'RING';
  from_node: string;
  to_node: string;
  lanes: number;
  speed_limit_kmh: number;
  capacity_veh_h: number;
  length_m: number;
  points: WorldPosition[];
}

export interface JunctionModel {
  id: string;
  name?: string | null;
  position: WorldPosition;
  kind: string;
}

export interface TransitStopModel {
  id: string;
  name: string;
  position: WorldPosition;
  kind: 'BUS' | 'TRAM' | 'RAIL';
}

export interface ParkingAreaModel {
  id: string;
  name: string;
  position: WorldPosition;
  capacity: number;
}

export interface ExternalEnvironment {
  venue_id: string;
  source: 'BUNDLED' | 'LIVE_OSM';
  origin?: string | null;
  bbox: Record<string, number>;
  roads: RoadSegmentModel[];
  junctions: JunctionModel[];
  transit: TransitStopModel[];
  parking: ParkingAreaModel[];
  notes: string[];
}

export interface ExternalElementState {
  id: string;
  kind: 'ROAD' | 'JUNCTION' | 'TRANSIT' | 'PARKING';
  people_accumulated: number;
  queue_veh: number;
  congestion: number;
  clearance_min?: number | null;
  risk: RiskLevel;
}

export interface ExternalState {
  venue_id: string;
  source: string;
  elements: Record<string, ExternalElementState>;
  congested_elements: number;
  risk: RiskLevel;
  summary: string;
}

// --------------------------------------------------------------------------- //
//  AI natural-language interface (backend /api/ai/*)
// --------------------------------------------------------------------------- //
export interface AiProviderStatus {
  configured: boolean;
  provider: string | null;
  models: Record<string, string[]>;
  missing: string[];
}

export interface ScenarioDelta {
  summary?: string;
  notes?: string[];
  name_suffix?: string;
  crowd_size?: number | null;
  event_end_delta_minutes?: number | null;
  gate_distribution?: Record<string, number> | null;
  exit_distribution?: Record<string, number> | null;
  destination_distribution?: Record<string, number> | null;
  close_gates?: string[];
  open_gates?: string[];
  close_edges?: string[];
  open_edges?: string[];
  incident?: IncidentModel | null;
  weather?: WeatherModel | null;
}

export interface AiInterpretResponse {
  delta: ScenarioDelta;
  provider: string;
  model: string;
  confidence: number;
  reasoning: string;
  warnings?: string[];
}

export interface AiExplainResponse {
  provider: string;
  summary: string;
  cause: string;
  try_actions: { type: InterventionType; description: string; parameters: Record<string, unknown> }[];
}

export interface AiSuggestion {
  id?: string;
  title: string;
  description: string;
  delta: ScenarioDelta;
}

export interface AiSuggestResponse {
  provider: string;
  suggestions: AiSuggestion[];
}