import * as THREE from 'three';
import type {
  AgentModel,
  OpeningType,
  Point2D,
  StructureModel,
  StructureType,
} from '../../lib/types';

// --------------------------------------------------------------------------- //
//  Coordinate frame: backend geometry is in raw meters (0..width, 0..height).
//  We center the world on the origin so the camera/orbit controls are stable.
// --------------------------------------------------------------------------- //
export interface Frame {
  w: number;
  h: number;
  toWorld: (x: number, y: number, elevation?: number) => [number, number, number];
  toLocalX: (x: number) => number;
  toLocalZ: (y: number) => number;
  centerX: number;
  centerZ: number;
}

export function makeFrame(width: number, height: number): Frame {
  return {
    w: width,
    h: height,
    centerX: width / 2,
    centerZ: height / 2,
    toLocalX: (x) => x - width / 2,
    toLocalZ: (y) => -(y - height / 2),
    toWorld: (x, y, elevation = 0) => [x - width / 2, elevation, -(y - height / 2)],
  };
}

export function polygonShape(points: Point2D[]): THREE.Shape {
  const shape = new THREE.Shape();
  if (!points.length) return shape;
  shape.moveTo(points[0].x, points[0].y);
  for (let i = 1; i < points.length; i++) shape.lineTo(points[i].x, points[i].y);
  shape.closePath();
  return shape;
}

export function extrudePolygon(points: Point2D[], depth: number, frame: Frame, elevation: number): THREE.ExtrudeGeometry {
  const geo = new THREE.ExtrudeGeometry(polygonShape(points), {
    depth: Math.max(0.05, depth),
    bevelEnabled: false,
  });
  geo.rotateX(-Math.PI / 2);
  geo.translate(-frame.centerX, elevation, frame.centerZ);
  geo.computeVertexNormals();
  return geo;
}

export function polygonCentroid(points: Point2D[]): Point2D {
  const n = points.length;
  if (!n) return { x: 0, y: 0 };
  const c = points.reduce((acc, p) => ({ x: acc.x + p.x / n, y: acc.y + p.y / n }), { x: 0, y: 0 });
  return c;
}

export interface TierDef {
  points: Point2D[];
  elevation: number;
  depth: number;
}

/** Split a structure into stepped tiers (for seating bowls / stands) or a single slab. */
export function structureTiers(s: StructureModel, elevation: number): TierDef[] {
  const height = Math.max(0.05, s.height_m ?? 2.0);
  const raw = Number(s.metadata?.tiers ?? 0);
  const tiers = Number.isFinite(raw) && raw > 1 ? Math.min(8, Math.floor(raw)) : 0;
  if (tiers === 0) return [{ points: s.polygon.points, elevation, depth: height }];
  const c = polygonCentroid(s.polygon.points);
  const step = height / tiers;
  const out: TierDef[] = [];
  for (let i = 0; i < tiers; i++) {
    const k = (tiers - i) / tiers;
    out.push({
      points: s.polygon.points.map((p) => ({ x: c.x + (p.x - c.x) * k, y: c.y + (p.y - c.y) * k })),
      elevation: elevation + i * step,
      depth: step,
    });
  }
  return out;
}

/** A walkable band following a path centerline, with a given width. */
export function bandGeometry(points: Point2D[], width: number, frame: Frame, elevation: number): THREE.ShapeGeometry {
  const half = Math.max(0.2, width) / 2;
  const left: Point2D[] = [];
  const right: Point2D[] = [];
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    const a = points[Math.max(0, i - 1)];
    const b = points[Math.min(points.length - 1, i + 1)];
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    const nx = -dy / len;
    const ny = dx / len;
    left.push({ x: p.x + nx * half, y: p.y + ny * half });
    right.push({ x: p.x - nx * half, y: p.y - ny * half });
  }
  const shape = new THREE.Shape();
  shape.moveTo(left[0].x, left[0].y);
  for (let i = 1; i < left.length; i++) shape.lineTo(left[i].x, left[i].y);
  for (let i = right.length - 1; i >= 0; i--) shape.lineTo(right[i].x, right[i].y);
  shape.closePath();
  const geo = new THREE.ShapeGeometry(shape);
  geo.rotateX(-Math.PI / 2);
  geo.translate(-frame.centerX, elevation, frame.centerZ);
  geo.computeVertexNormals();
  return geo;
}

// --------------------------------------------------------------------------- //
//  Palette (dark default twin theme)
// --------------------------------------------------------------------------- //
export interface TwinPalette {
  canvas: string;
  ink: string;
  muted: string;
  line: string;
  slabTop: string;
  slabFront: string;
  slabSide: string;
  ok: string;
  warn: string;
  danger: string;
}

export const TWIN_PALETTE: TwinPalette = {
  canvas: '#0f1115',
  ink: '#e2e8f0',
  muted: '#64748b',
  line: '#334155',
  slabTop: '#161a20',
  slabFront: '#232a34',
  slabSide: '#2e3944',
  ok: '#10b981',
  warn: '#f59e0b',
  danger: '#ef4444',
};

export const STRUCTURE_COLOR: Record<StructureType, string | undefined> = {
  FLOOR: undefined,
  WALL: undefined,
  FIELD: '#1e5630',
  SEATING: undefined,
  CONCOURSE: undefined,
  ROOM: undefined,
  STAIR: '#4a525c',
  ROOF: undefined,
  ZONE: '#3d2f8f',
  STAIRS: '#4a525c',
  COLUMN: '#3c4650',
  OBSTACLE: '#7a3f06',
  VOMITORY: undefined,
};

export const ROOM_KIND_COLOR: Record<string, string> = {
  CONCESSION: '#7a5213',
  CHECKPOINT: '#4a33a8',
};

export const OPENING_COLOR: Record<OpeningType, string> = {
  ENTRY_GATE: '#10b981',
  EXIT_GATE: '#f59e0b',
  EMERGENCY_EXIT: '#ef4444',
  DOOR: '#4a525c',
  WINDOW: '#2f7ea0',
};

// --------------------------------------------------------------------------- //
//  Seats: procedural rows along a tier perimeter (instanced).
// --------------------------------------------------------------------------- //
export interface SeatInfo {
  pos: [number, number, number];
  rot: number;
}

export function generateSeatsForTier(points: Point2D[], elevation: number, frame: Frame): SeatInfo[] {
  const seats: SeatInfo[] = [];
  if (points.length < 3) return seats;
  const c = polygonCentroid(points);
  const offsetPoints: Point2D[] = points.map((p) => {
    const dx = p.x - c.x;
    const dy = p.y - c.y;
    const dist = Math.hypot(dx, dy) || 1;
    const shrink = Math.max(0.1, dist - 0.5);
    return { x: c.x + (dx / dist) * shrink, y: c.y + (dy / dist) * shrink };
  });
  const spacing = 0.75;
  for (let i = 0; i < offsetPoints.length; i++) {
    const p1 = offsetPoints[i];
    const p2 = offsetPoints[(i + 1) % offsetPoints.length];
    const dx = p2.x - p1.x;
    const dy = p2.y - p1.y;
    const len = Math.hypot(dx, dy);
    if (len < 0.1) continue;
    const numSeats = Math.floor(len / spacing);
    const angle = Math.atan2(-dy, dx);
    for (let j = 0; j < numSeats; j++) {
      const t = j / numSeats;
      const [wx, wy, wz] = frame.toWorld(p1.x + dx * t, p1.y + dy * t, elevation);
      seats.push({ pos: [wx, wy + 0.15, wz], rot: angle });
    }
  }
  return seats;
}

// --------------------------------------------------------------------------- //
//  Crowd agents → an instanced mesh positioned inside the twin.
// --------------------------------------------------------------------------- //
export function applyAgents(
  mesh: THREE.InstancedMesh | null,
  agents: AgentModel[],
  frame: Frame,
  time: number,
  palette: TwinPalette,
): void {
  if (!mesh) return;
  const dummy = new THREE.Object3D();
  const col = new THREE.Color();
  const count = Math.min(agents.length, mesh.count);
  for (let i = 0; i < count; i++) {
    const a = agents[i];
    const bob = a.speed_mps > 0 ? Math.sin(time * Math.min(12, a.speed_mps * 6)) * 0.1 : 0;
    const [wx, wy, wz] = frame.toWorld(a.position.x, a.position.y, 0.9 + bob);
    dummy.position.set(wx, wy, wz);
    dummy.scale.set(1, 1, 1);
    dummy.updateMatrix();
    mesh.setMatrixAt(i, dummy.matrix);
    col.set(a.is_emergency ? palette.danger : a.is_rerouted ? palette.warn : palette.ok);
    mesh.setColorAt(i, col);
  }
  mesh.count = count;
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
}
