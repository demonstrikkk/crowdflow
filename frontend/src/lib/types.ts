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
export type WeatherCondition =
  | 'HEAVY_RAIN' | 'RAIN' | 'HAIL' | 'HEAT' | 'FOG' | 'CLEAR' | 'STORM';

export type GroupType =
  | 'INDIVIDUAL' | 'FAMILY' | 'FRIENDS' | 'FANS'
  | 'VIP' | 'STAFF' | 'VENDOR' | 'MEDIA' | 'EMERGENCY';

export type AgentIntention =
  | 'ENTER' | 'SEAT' | 'TOILET' | 'CONCESSION'
  | 'EXIT' | 'SHADE' | 'WATER';

export type ViewMode =
  | 'command' | 'stadium' | 'crowd' | 'agent'
  | 'security' | 'density' | 'flow' | 'route'
  | 'emergency' | 'weather' | 'behaviour' | 'infrastructure'
  | 'replay' | 'compare';


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
  spatial_ref?: string | null;
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
  geometry_id?: string | null;
}

export interface VenueModel {
  id: string;
  name: string;
  width: number;
  height: number;
  nodes: NodeModel[];
  edges: EdgeModel[];
}

// --------------------------------------------------------------------------- //
//  VenueSpatialModel (architectural twin: walls, structures, openings, paths)
// --------------------------------------------------------------------------- //
export interface Point2D {
  x: number;
  y: number;
}

export interface Polygon2D {
  points: Point2D[];
}

export interface LevelModel {
  id: string;
  name: string;
  elevation_m?: number;
  height_m?: number;
}

export type StructureType =
  | 'FLOOR'
  | 'WALL'
  | 'FIELD'
  | 'SEATING'
  | 'CONCOURSE'
  | 'ROOM'
  | 'STAIR'
  | 'ROOF'
  | 'ZONE'
  | 'STAIRS'
  | 'COLUMN'
  | 'OBSTACLE'
  | 'VOMITORY';

export interface StructureModel {
  id: string;
  level_id: string;
  type: StructureType;
  polygon: Polygon2D;
  height_m?: number;
  metadata?: Record<string, unknown>;
}

export type OpeningType = 'ENTRY_GATE' | 'EXIT_GATE' | 'EMERGENCY_EXIT' | 'DOOR' | 'WINDOW';

export interface OpeningModel {
  id: string;
  level_id: string;
  type: OpeningType;
  position: Point2D;
  width_m?: number;
  rotation_deg?: number;
  is_emergency?: boolean;
  metadata?: Record<string, unknown>;
}

export interface PathGeometryModel {
  id: string;
  level_id: string;
  centerline: Point2D[];
  width_m?: number;
  metadata?: Record<string, unknown>;
}

export interface VenueSpatialModel {
  venue_id: string;
  coordinate_system?: string;
  levels: LevelModel[];
  structures: StructureModel[];
  openings: OpeningModel[];
  paths: PathGeometryModel[];
  metadata?: Record<string, unknown>;
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

export type ElementReportStatus = 'ACCEPTED' | 'REVIEW' | 'REJECTED';

export interface ElementReport {
  id: string;
  kind: string;
  confidence: number;
  source: string;
  status: ElementReportStatus;
  warning?: string | null;
}

export interface ReconstructionReport {
  summary: string;
  overall_confidence: number;
  elements: ElementReport[];
  warnings: string[];
  unresolved: string[];
}

export interface BlueprintResult {
  venue: VenueModel;
  spatial?: VenueSpatialModel | null;
  elements: BlueprintElement[];
  confidence: number;
  degradation_level: number;
  degraded: boolean;
  steps: Record<string, string>;
  notes: string[];
  report?: ReconstructionReport | null;
}

export type DetectionKind =
  | 'WALL'
  | 'BOUNDARY'
  | 'REGION'
  | 'ROOM'
  | 'ZONE'
  | 'FIELD'
  | 'SEATING'
  | 'CONCOURSE'
  | 'DOOR'
  | 'GATE'
  | 'STAIR'
  | 'CORRIDOR'
  | 'TEXT';

export interface Point2D {
  x: number;
  y: number;
}

export interface Detection {
  id: string;
  kind: DetectionKind;
  geometry: {
    type: 'SEGMENT' | 'POLYGON' | 'POINT' | 'POLYLINE';
    point?: Point2D | null;
    p0?: Point2D | null;
    p1?: Point2D | null;
    polygon?: Point2D[] | null;
    polyline?: Point2D[] | null;
    bbox?: [number, number, number, number] | null;
  };
  text?: string | null;
  confidence: number;
  source?: string;
  level_id?: string;
  metadata: Record<string, unknown>;
}

export interface BlueprintImageMeta {
  filename: string;
  format: string;
  page: number;
  pages: number;
  width_px: number;
  height_px: number;
  deskew_deg: number;
  width_m: number;
  height_m: number;
  scale_m_per_px: number;
}

export interface BlueprintDetectionResult {
  image: BlueprintImageMeta;
  detections: Detection[];
  provider: string;
  warnings: string[];
  gemini_analysis?: Record<string, unknown> | null;
  architectural_scene?: ArchitecturalScene | null;
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
  patience: number;
  stress: number;
  excitement: number;
  fatigue: number;
  heat_exposure: number;
  hydration: number;
  perceived_crowding: number;
  incident_awareness: boolean;
  group_id: string | null;
  group_type: GroupType;
  current_intention: AgentIntention;
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
  condition: WeatherCondition | string;
  temperature: number;
  humidity: number;
  wind_speed_mps: number;
  visibility: number;
  uv_index: number;
  heat_index: number;
  capacity_multiplier: number;
  speed_multiplier: number;
  unsafe_outdoor: boolean;
  applies_outdoor_only?: boolean;
}

// Causal influence graph (built server-side each tick)
export interface CausalNode {
  id: string;
  label: string;
  value: string;
  state: 'NORMAL' | 'WARNING' | 'CRITICAL';
}

export interface CausalLink {
  source: string;
  target: string;
  label: string | null;
}

export interface CausalGraph {
  nodes: CausalNode[];
  links: CausalLink[];
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
  // Living crowd state aggregates
  avg_stress: number;
  avg_fatigue: number;
  avg_patience: number;
  avg_hydration: number;
  water_seekers: number;
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
  world?: WorldState | null;
  causal_graph?: CausalGraph | null;
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
//  World layer — unified external graph (backend /api/world + sim.world)
//  The map is part of the simulation: demand sources route over the external
//  graph to venue gates, and the venue drains back to outer sinks.
// --------------------------------------------------------------------------- //
export interface WorldNode {
  id: string;
  kind: 'ROAD' | 'FOOTPATH' | 'TRANSIT' | 'PARKING' | 'GATE_LINK' | 'SINK' | string;
  position: WorldPosition;
  name?: string | null;
  lat?: number | null;
  lon?: number | null;
  source: string;
}

export interface WorldEdge {
  id: string;
  source: string;
  target: string;
  kind: 'ROAD' | 'FOOTPATH' | 'STREET' | 'GATE_LINK' | string;
  length_m: number;
  walking_allowed: boolean;
  road_allowed: boolean;
  capacity_estimate: number;
  speed_mps: number;
  free_flow_min: number;
  geometry: WorldPosition[];
  capacity_source: 'estimated' | 'measured' | string;
  closed?: boolean;
}

export interface WorldAccessPoint {
  id: string;
  gate_id: string;
  node_id: string;
  kind: 'ENTRY' | 'EXIT' | 'EMERGENCY_EXIT';
  position: WorldPosition;
  service_ppm: number;
}

export interface WorldDemandSource {
  id: string;
  kind: 'METRO' | 'BUS' | 'PARKING' | 'DROP_OFF' | 'WALKING' | 'GATHERING' | string;
  name: string;
  node_id: string;
  position: WorldPosition;
  capacity: number;
  share: number;
  gate_share: Record<string, number>;
  data_source: 'SIMULATED' | 'HISTORICAL' | 'LIVE' | 'USER_INPUT';
}

export interface WorldProvenance {
  provider: 'OSM' | 'DEMO' | 'CACHED_OSM' | string;
  fetched_at?: string | null;
  confidence: 'high' | 'estimated' | 'demo' | string;
  notes: string[];
}

export interface WorldBbox {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
}

export interface WorldGraph {
  venue_id: string;
  provider: 'OSM' | 'DEMO' | 'CACHED_OSM' | string;
  provenance: WorldProvenance;
  bbox: WorldBbox;
  nodes: WorldNode[];
  edges: WorldEdge[];
  access_points: WorldAccessPoint[];
  demand_sources: WorldDemandSource[];
  sink_ids: string[];
  notes: string[];
}

export interface WorldEdgeState {
  id: string;
  kind: string;
  flow_per_min: number;
  people: number;
  utilisation: number;
  congestion: number;
  risk: RiskLevel;
  time_to_critical_min?: number | null;
  closed: boolean;
  rerouted: boolean;
  // Per-mode flow for truthful transport rendering: walk (people/min) plus
  // car/bus/metro (vehicles/min). Derived from the demand plan.
  flow_by_mode?: Record<string, number>;
}

export interface WorldGateState {
  gate_id: string;
  arrivals_per_min: number;
  served_per_min: number;
  queue: number;
  queue_wait_min?: number | null;
  congestion: number;
  risk: RiskLevel;
  demand_by_source: Record<string, number>;
}

export interface WorldSourceState {
  id: string;
  kind: string;
  emitted_total: number;
  current_rate_per_min: number;
  // Approach mode: walk | car | bus | metro; vehicles_per_min is derived from
  // the demand plan (people ÷ occupancy), never fabricated.
  mode?: string;
  vehicles_per_min?: number;
}

export interface WorldPrediction {
  id: string;
  kind: 'EDGE' | 'GATE' | 'ROUTE';
  ref: string;
  in_minutes: number;
  severity: RiskLevel;
  message: string;
}

export interface WorldState {
  t_min: number;
  edges: Record<string, WorldEdgeState>;
  gates: Record<string, WorldGateState>;
  sources: Record<string, WorldSourceState>;
  risk: RiskLevel;
  congested_edges: number;
  summary: string;
  predictions: WorldPrediction[];
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

// ---------------------------------------------------------------------------
//  Architectural Scene types (spec §60)
//  These mirror the Python Pydantic models in architecture/models.py
// ---------------------------------------------------------------------------

export type EntityType =
  | 'FIELD' | 'SEATING_BOWL' | 'SEATING_BLOCK' | 'CONCOURSE' | 'CORRIDOR'
  | 'AISLE' | 'VOMITORY' | 'STAIR' | 'RAMP' | 'ELEVATOR' | 'ENTRY' | 'EXIT'
  | 'EMERGENCY_EXIT' | 'SERVICE_ENTRY' | 'CHECKPOINT' | 'CONCESSION'
  | 'CAFETERIA' | 'WASHROOM' | 'MEDICAL' | 'VIP' | 'MEDIA' | 'SERVICE'
  | 'ROOM' | 'WALL' | 'COLUMN' | 'ROOF' | 'ZONE';

export type EntitySource = 'BLUEPRINT' | 'GEMINI' | 'FLORENCE' | 'CV' | 'FUSED' | 'PROCEDURAL' | 'USER';

export interface ArchitecturalLocation {
  normalized_x?: number | null;
  normalized_y?: number | null;
  normalized_polygon?: [number, number][] | null;
  description?: string | null;
}

export interface EvidenceItem {
  source: EntitySource;
  description: string;
  confidence: number;
}

export interface ArchitecturalRegion {
  id: string;
  type: EntityType;
  label: string;
  level_id: string;
  location: ArchitecturalLocation;
  confidence: number;
  source: EntitySource;
  evidence: EvidenceItem[];
  metadata: Record<string, unknown>;
}

export interface ArchitecturalOpening {
  id: string;
  type: EntityType;
  label: string;
  level_id: string;
  location: ArchitecturalLocation;
  confidence: number;
  source: EntitySource;
  evidence: EvidenceItem[];
  capacity_ppm?: number | null;
  is_emergency?: boolean;
  metadata: Record<string, unknown>;
}

export interface ArchitecturalFacility {
  id: string;
  type: EntityType;
  label: string;
  level_id: string;
  location: ArchitecturalLocation;
  confidence: number;
  source: EntitySource;
  evidence: EvidenceItem[];
  metadata: Record<string, unknown>;
}

export interface ArchitecturalLevel {
  id: string;
  name: string;
  level_index: number;
  elevation_m?: number | null;
  floor_height_m?: number | null;
  label?: string | null;
  confidence: number;
}

export interface ArchitecturalRelationship {
  source_id: string;
  relation: string;
  target_id: string;
  confidence: number;
}

export interface VerticalConnection {
  id: string;
  type: EntityType;
  label: string;
  level_id: string;
  from_level_id: string;
  to_level_id: string;
  location: ArchitecturalLocation;
  confidence: number;
  source: EntitySource;
  evidence: EvidenceItem[];
  metadata: Record<string, unknown>;
}

export interface ScaleEvidence {
  meters_per_px: number;
  confidence: number;
  source: string;
  note?: string | null;
}

export interface ArchitecturalUncertainty {
  element_id?: string | null;
  description: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH';
}

export interface ArchitecturalVenue {
  venue_type: string;
  footprint_shape?: string | null;
  center_normalized?: [number, number] | null;
  orientation_deg?: number | null;
  field_type?: string | null;
  confidence: number;
}

export interface ArchitecturalDocument {
  type: string;
  projection: string;
  venue_type: string;
  floor_or_level?: string | null;
  orientation?: string | null;
  image_quality: string;
  confidence: number;
}

export interface ArchitecturalScene {
  document: ArchitecturalDocument;
  venue: ArchitecturalVenue;
  levels: ArchitecturalLevel[];
  regions: ArchitecturalRegion[];
  openings: ArchitecturalOpening[];
  facilities: ArchitecturalFacility[];
  vertical_connections: VerticalConnection[];
  relationships: ArchitecturalRelationship[];
  scale: ScaleEvidence;
  uncertainties: ArchitecturalUncertainty[];
  confidence: number;
}

export interface ReconstructionQuality {
  passed: boolean;
  reasons: string[];
  document_confidence: number;
  geometry_confidence: number;
  semantic_confidence: number;
  seating_confidence: number;
  level_confidence: number;
  gate_confidence: number;
  navigation_confidence: number;
  overall_confidence: number;
  scale_confidence?: number;
  warnings: string[];
  procedural_completion_count: number;
  blueprint_derived_count: number;
}

export interface StadiumProfile {
  venue_id: string;
  stadium_type: string;
  structural_style: string;
  roof_strategy: string;
  footprint_shape: string;
  footprint_width_m: number;
  footprint_depth_m: number;
  field_width_m: number;
  field_depth_m: number;
  seating_bowl_count: number;
  concourse_count: number;
  gate_count: number;
  level_ids: string[];
}

// --------------------------------------------------------------------------- //
//  Venue Digital Twin (canonical semantic model) — mirrors backend models.py
//  The twin is a validated, editable, renderer-agnostic semantic model. The
//  3D scene is always a *projection* of this model; geometry is produced by
//  deterministic generators, never by per-object AI mesh code.
// --------------------------------------------------------------------------- //
export type TwinSeverity = 'ERROR' | 'WARNING' | 'INFERENCE';

export interface TwinValidationIssue {
  id: string;
  severity: TwinSeverity;
  scope: string;
  message: string;
  element_ids: string[];
}

export interface TwinNavigationNode {
  id: string;
  type: NodeType;
  position: Point2D;
  level_id: string;
  capacity: number;
  confidence: number;
  spatial_ref?: string | null;
}

export interface TwinNavigationEdge {
  id: string;
  source: string;
  destination: string;
  length_m: number;
  width_m: number;
  capacity_ppm: number;
  level_change: number;
  is_emergency: boolean;
  geometry_id?: string | null;
}

export interface TwinNavigationGraph {
  nodes: TwinNavigationNode[];
  edges: TwinNavigationEdge[];
}

export interface TwinCoordinateSystem {
  name: string;
  units: string;
  origin: Point2D;
  north_deg: number;
  scale_estimated: boolean;
  source?: string | null;
}

export interface TwinDimensions {
  width_m: number;
  height_m: number;
}

export interface TwinLevel {
  id: string;
  name: string;
  index: number;
  elevation_m: number;
  height_m: number;
}

export interface TwinStructure {
  id: string;
  type: StructureType;
  level_id: string;
  polygon: Polygon2D;
  height_m: number;
  confidence: number;
  source: string;
  metadata: Record<string, unknown>;
}

export interface TwinOpening {
  id: string;
  type: OpeningType;
  level_id: string;
  position: Point2D;
  width_m: number;
  rotation_deg: number;
  capacity_ppm: number;
  is_emergency: boolean;
  confidence: number;
  source: string;
  metadata: Record<string, unknown>;
}

export interface TwinPath {
  id: string;
  level_id: string;
  centerline: Point2D[];
  width_m: number;
  confidence: number;
  source: string;
  metadata: Record<string, unknown>;
}

export interface TwinRoad {
  id: string;
  kind: string;
  name?: string | null;
  lanes: number;
  width_m: number;
  capacity_veh_h: number;
  points: Point2D[];
}

export interface TwinSite {
  roads: TwinRoad[];
  notes: string[];
}

export interface TwinSourceReference {
  element_id: string;
  kind: string;
  source_bbox?: number[] | null;
  note?: string | null;
}

export interface VenueDigitalTwin {
  venue_id: string;
  name: string;
  coordinate_system: TwinCoordinateSystem;
  dimensions: TwinDimensions;
  levels: TwinLevel[];
  structures: TwinStructure[];
  openings: TwinOpening[];
  paths: TwinPath[];
  navigation: TwinNavigationGraph;
  site: TwinSite;
  validation: TwinValidationIssue[];
  confidence: number;
  metadata: Record<string, unknown>;
  source_references: TwinSourceReference[];
}

// --------------------------------------------------------------------------- //
//  AI 3D Digital Twin generation (backend /api/twin/*)
//  A TwinGenerationJob turns a blueprint image into a GLB + semantic model
//  (venue.glb / venue.semantic.json / generation.metadata.json) via a provider
//  that may be a local procedural pipeline, a simulated mock, or a remote
//  Colab GPU worker. Provenance is always reported honestly.
// --------------------------------------------------------------------------- //
export type TwinProvenance = 'AI' | 'PROCEDURAL' | 'SIMULATED';
export type TwinStage =
  | 'QUEUED' | 'DOWNLOADING' | 'ANALYZING' | 'GENERATING_GEOMETRY'
  | 'GENERATING_TEXTURE' | 'SEMANTIC_PROCESSING' | 'EXPORTING'
  | 'COMPLETE' | 'FAILED';
export type TwinJobStatus = 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';

export interface TwinArtifact {
  name: string;
  kind: 'GLB' | 'SEMANTIC' | 'METADATA' | 'PREVIEW' | 'INPUT';
  path: string;
  size_bytes: number;
  mime: string;
}

export type TwinBindingKind = 'ENTRY_GATE' | 'EXIT_GATE' | 'EMERGENCY_EXIT' | 'ZONE' | 'PATH';

export interface TwinBinding {
  node_id: string;
  kind: TwinBindingKind;
  spatial_id: string;
  glb_node: string;
  glb_mesh: string;
  simulation_node: string;
}

export interface TwinGenerationJob {
  id: string;
  provider: string;
  model: string;
  provenance: TwinProvenance;
  status: TwinJobStatus;
  stage: TwinStage;
  progress: number;
  error?: string | null;
  venue_id?: string | null;
  scenario_id?: string | null;
  created_at: string;
  updated_at: string;
  artifacts: TwinArtifact[];
  bindings: TwinBinding[];
  metadata: Record<string, unknown>;
  logs: string[];
}

export interface TwinProviderStatus {
  provider: string;
  model: string;
  online: boolean;
  provenance: TwinProvenance;
  reason?: string | null;
}