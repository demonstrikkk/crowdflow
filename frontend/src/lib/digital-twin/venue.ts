import type {
  StructureType,
  VenueDigitalTwin,
  VenueModel,
  VenueSpatialModel,
} from '../types';
import { validateTwin } from './validator';

// --------------------------------------------------------------------------- //
//  Mapping between the persistence model (VenueDocument / VenueSpatialModel) and
//  the canonical VenueDigitalTwin. The twin is renderer-agnostic; the renderer
//  projects it, never the other way around.
// --------------------------------------------------------------------------- //

export function twinToSpatial(twin: VenueDigitalTwin): VenueSpatialModel {
  return {
    venue_id: twin.venue_id,
    coordinate_system: 'LOCAL_METRIC',
    levels: twin.levels.map((lv) => ({
      id: lv.id,
      name: lv.name,
      elevation_m: lv.elevation_m,
      height_m: lv.height_m,
    })),
    structures: twin.structures.map((s) => ({
      id: s.id,
      level_id: s.level_id,
      type: s.type,
      polygon: s.polygon,
      height_m: s.height_m,
      metadata: s.metadata,
    })),
    openings: twin.openings.map((o) => ({
      id: o.id,
      level_id: o.level_id,
      type: o.type,
      position: o.position,
      width_m: o.width_m,
      rotation_deg: o.rotation_deg,
      metadata: o.metadata,
    })),
    paths: twin.paths.map((p) => ({
      id: p.id,
      level_id: p.level_id,
      centerline: p.centerline,
      width_m: p.width_m,
      metadata: p.metadata,
    })),
    metadata: twin.metadata,
  };
}

const STRUCTURE_CONFIDENCE_BY_SOURCE: Record<string, number> = {
  AUTHORED: 0.95,
  BLUEPRINT: 0.8,
  DERIVED: 0.7,
  USER: 0.9,
};

export function sourceConfidence(source: string, fallback: number): number {
  return STRUCTURE_CONFIDENCE_BY_SOURCE[source] ?? fallback;
}

/** Confidence map for meshes — used by the CONFIDENCE visual mode. */
export function structureConfidence(twin: VenueDigitalTwin): Map<string, number> {
  const map = new Map<string, number>();
  for (const s of twin.structures) map.set(s.id, s.confidence);
  return map;
}

/** Client-side twin builder fallback when the backend /twin endpoint is absent. */
export function twinFromSpatial(venue: VenueModel, spatial: VenueSpatialModel): VenueDigitalTwin {
  const openingById = new Map(spatial.openings.map((o) => [o.id, o]));
  const twin: VenueDigitalTwin = {
    venue_id: venue.id,
    name: venue.name,
    coordinate_system: {
      name: 'LOCAL_METRIC',
      units: 'm',
      origin: { x: 0, y: 0 },
      north_deg: 0,
      scale_estimated: spatial.metadata?.source !== 'AUTHORED',
      source: String(spatial.metadata?.source ?? 'DERIVED'),
    },
    dimensions: { width_m: venue.width, height_m: venue.height },
    levels: spatial.levels.map((lv, i) => ({
      id: lv.id,
      name: lv.name,
      index: i,
      elevation_m: lv.elevation_m ?? 0,
      height_m: lv.height_m ?? 5,
    })),
    structures: spatial.structures.map((s) => ({
      id: s.id,
      type: s.type,
      level_id: s.level_id,
      polygon: s.polygon,
      height_m: s.height_m ?? 2,
      confidence: sourceConfidence(String(s.metadata?.source ?? 'PROCEDURAL'), 0.7),
      source: String(s.metadata?.source ?? 'PROCEDURAL'),
      metadata: s.metadata ?? {},
    })),
    openings: spatial.openings.map((o) => ({
      id: o.id,
      type: o.type,
      level_id: o.level_id,
      position: o.position,
      width_m: o.width_m ?? 4,
      rotation_deg: o.rotation_deg ?? 0,
      capacity_ppm: 120,
      is_emergency: o.type === 'EMERGENCY_EXIT',
      confidence: sourceConfidence(String(o.metadata?.source ?? 'PROCEDURAL'), 0.7),
      source: String(o.metadata?.source ?? 'PROCEDURAL'),
      metadata: o.metadata ?? {},
    })),
    paths: spatial.paths.map((p) => ({
      id: p.id,
      level_id: p.level_id,
      centerline: p.centerline,
      width_m: p.width_m ?? 3,
      confidence: sourceConfidence(String(p.metadata?.source ?? 'PROCEDURAL'), 0.7),
      source: String(p.metadata?.source ?? 'PROCEDURAL'),
      metadata: p.metadata ?? {},
    })),
    navigation: {
      nodes: venue.nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        level_id: openingById.get(n.id)?.level_id ?? 'L1',
        capacity: n.capacity ?? 0,
        confidence: sourceConfidence(String(n.metadata?.source ?? 'PROCEDURAL'), 0.8),
        spatial_ref: n.spatial_ref,
      })),
      edges: venue.edges.map((e) => ({
        id: e.id,
        source: e.source,
        destination: e.destination,
        length_m: e.length_m,
        width_m: e.width_m,
        capacity_ppm: e.capacity,
        level_change: 0,
        is_emergency: e.is_emergency,
        geometry_id: e.geometry_id,
      })),
    },
    site: { roads: [], notes: [] },
    validation: [],
    confidence: 0.75,
    metadata: spatial.metadata ?? {},
    source_references: [],
  };
  twin.validation = validateTwin(twin);
  return twin;
}

export function structureDisplayType(type: StructureType): string {
  switch (type) {
    case 'FIELD':
      return 'FIELD / PITCH';
    case 'CONCOURSE':
      return 'CONCOURSE';
    case 'VOMITORY': // eslint-disable-line no-case-declarations
      return 'VOMITORY';
    default:
      return type;
  }
}