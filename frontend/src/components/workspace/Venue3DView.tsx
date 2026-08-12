import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Grid, Html, OrbitControls } from '@react-three/drei';
import {
  Box,
  Camera,
  Layers,
  PanelsTopLeft,
  RefreshCw,
  Shield,
  TriangleAlert,
  Sliders,
  Eye,
  Activity,
  Save,
  CheckCircle,
} from 'lucide-react';
import * as THREE from 'three';
import { api } from '../../lib/api';
import type {
  AgentModel,
  LevelModel,
  OpeningModel,
  OpeningType,
  PathGeometryModel,
  Point2D,
  StructureModel,
  StructureType,
  VenueSpatialModel,
} from '../../lib/types';
import { useSimulation } from '../../store/SimulationContext';
import InstrumentCanvas from './InstrumentCanvas';

// --------------------------------------------------------------------------- //
//  View Modes & Theme Definitions
// --------------------------------------------------------------------------- //
type ViewMode = 'architectural' | 'circulation' | 'simulation' | 'confidence';

interface Frame {
  w: number;
  h: number;
  toWorld: (x: number, y: number, elevation?: number) => [number, number, number];
  centerX: number;
  centerZ: number;
}

function makeFrame(width: number, height: number): Frame {
  return {
    w: width,
    h: height,
    centerX: width / 2,
    centerZ: height / 2,
    toWorld: (x, y, elevation = 0) => [x - width / 2, elevation, -(y - height / 2)],
  };
}

export type PickTarget = { kind: 'structure' | 'opening' | 'path'; id: string };

// --------------------------------------------------------------------------- //
//  Geometry builders
// --------------------------------------------------------------------------- //
function polygonShape(points: Point2D[]): THREE.Shape {
  const shape = new THREE.Shape();
  if (points.length === 0) return shape;
  shape.moveTo(points[0].x, points[0].y);
  for (let i = 1; i < points.length; i++) shape.lineTo(points[i].x, points[i].y);
  shape.closePath();
  return shape;
}

function extrudePolygon(points: Point2D[], depth: number, frame: Frame, elevation: number): THREE.ExtrudeGeometry {
  const geo = new THREE.ExtrudeGeometry(polygonShape(points), {
    depth: Math.max(0.05, depth),
    bevelEnabled: false,
  });
  geo.rotateX(-Math.PI / 2);
  geo.translate(-frame.centerX, elevation, frame.centerZ);
  geo.computeVertexNormals();
  return geo;
}

function polygonCentroid(points: Point2D[]): Point2D {
  const n = points.length;
  if (n === 0) return { x: 0, y: 0 };
  const c = points.reduce((acc, p) => ({ x: acc.x + p.x / n, y: acc.y + p.y / n }), { x: 0, y: 0 });
  return c;
}

interface TierDef {
  points: Point2D[];
  elevation: number;
  depth: number;
}

function structureTiers(s: StructureModel, elevation: number): TierDef[] {
  const height = Math.max(0.05, s.height_m ?? 2.0);
  const raw = Number(s.metadata?.tiers ?? 0);
  const tiers = Number.isFinite(raw) && raw > 1 ? Math.min(8, Math.floor(raw)) : 0;
  if (tiers === 0) {
    return [{ points: s.polygon.points, elevation, depth: height }];
  }
  const c = polygonCentroid(s.polygon.points);
  const out: TierDef[] = [];
  const step = height / tiers;
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

function bandGeometry(points: Point2D[], width: number, frame: Frame, elevation: number): THREE.ShapeGeometry {
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
//  Procedural Seat Generation Algorithm
// --------------------------------------------------------------------------- //
interface SeatInfo {
  pos: [number, number, number];
  rot: number;
}

function generateSeatsForTier(points: Point2D[], elevation: number, frame: Frame): SeatInfo[] {
  const seats: SeatInfo[] = [];
  if (points.length < 3) return seats;
  
  // Calculate centroid
  const c = polygonCentroid(points);
  
  // Create an offset path for seats (slightly inside the step)
  const offsetPoints: Point2D[] = points.map((p) => {
    const dx = p.x - c.x;
    const dy = p.y - c.y;
    const dist = Math.hypot(dx, dy) || 1;
    const shrink = Math.max(0.1, dist - 0.35);
    return {
      x: c.x + (dx / dist) * shrink,
      y: c.y + (dy / dist) * shrink,
    };
  });

  const spacing = 0.75; // meters between seats
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
      const sx = p1.x + dx * t;
      const sy = p1.y + dy * t;
      const [wx, wy, wz] = frame.toWorld(sx, sy, elevation);
      seats.push({
        pos: [wx, wy + 0.1, wz],
        rot: angle,
      });
    }
  }
  return seats;
}

// --------------------------------------------------------------------------- //
//  Palette definitions
// --------------------------------------------------------------------------- //
interface Palette {
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

const THEME_PALETTES: Record<'light' | 'dark', Palette> = {
  light: {
    canvas: '#e8ebef',
    ink: '#10141a',
    muted: '#5d6670',
    line: '#a7b0b9',
    slabTop: '#f7f8fa',
    slabFront: '#dde2e7',
    slabSide: '#c6cdd4',
    ok: '#1b7f4c',
    warn: '#b06608',
    danger: '#c62b29',
  },
  dark: {
    canvas: '#070809',
    ink: '#e7eaed',
    muted: '#78818a',
    line: '#3a4149',
    slabTop: '#151a1f',
    slabFront: '#222a32',
    slabSide: '#2e3944',
    ok: '#3cb879',
    warn: '#e2a64f',
    danger: '#ff5c55',
  },
};

function usePalette(): Palette {
  const { theme } = useSimulation();
  return useMemo(() => THEME_PALETTES[theme], [theme]);
}

const STRUCTURE_COLOR: Record<StructureType, string | undefined> = {
  FLOOR: undefined,
  WALL: undefined,
  FIELD: '#2a6b3b',
  SEATING: undefined,
  CONCOURSE: undefined,
  ROOM: undefined,
  STAIR: '#6a727f',
  ROOF: undefined,
  ZONE: '#5035ba',
  STAIRS: '#6a727f',
  COLUMN: '#55606d',
  OBSTACLE: '#a65405',
  VOMITORY: undefined,
};

const ROOM_KIND_COLOR: Record<string, string> = {
  CONCESSION: '#a16c1b',
  CHECKPOINT: '#613ebe',
};

const OPENING_COLOR: Record<OpeningType, string> = {
  ENTRY_GATE: '#258250',
  EXIT_GATE: '#bf7d20',
  EMERGENCY_EXIT: '#ca332b',
  DOOR: '#6a727f',
  WINDOW: '#3b86a3',
};

function getConfidenceColor(conf: number): string {
  if (conf < 0.6) return '#ca332b'; // low: red
  if (conf < 0.85) return '#bf7d20'; // mid: orange
  return '#258250'; // high: green
}

// --------------------------------------------------------------------------- //
//  Procedural Field Markings Component
// --------------------------------------------------------------------------- //
function FieldMarkings({ points, frame }: { points: Point2D[]; frame: Frame }) {
  const lines = useMemo(() => {
    if (points.length < 3) return null;
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);

    const w = maxX - minX;
    const h = maxY - minY;
    const cx = minX + w / 2;
    const cy = minY + h / 2;

    const [worldCx, , worldCz] = frame.toWorld(cx, cy, 0.05);

    // Create field line geometry
    const lineGeo = new THREE.BufferGeometry();
    const vertices: number[] = [];

    // Helper to add segment
    const addSeg = (x1: number, y1: number, x2: number, y2: number) => {
      const [wx1, , wz1] = frame.toWorld(x1, y1, 0.05);
      const [wx2, , wz2] = frame.toWorld(x2, y2, 0.05);
      vertices.push(wx1, 0.05, wz1, wx2, 0.05, wz2);
    };

    // Boundary lines
    addSeg(minX + 1, minY + 1, maxX - 1, minY + 1);
    addSeg(maxX - 1, minY + 1, maxX - 1, maxY - 1);
    addSeg(maxX - 1, maxY - 1, minX + 1, maxY - 1);
    addSeg(minX + 1, maxY - 1, minX + 1, minY + 1);

    // Halfway line
    if (w > h) {
      addSeg(cx, minY + 1, cx, maxY - 1);
    } else {
      addSeg(minX + 1, cy, maxX - 1, cy);
    }

    lineGeo.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    return { lineGeo, center: [worldCx, 0.05, worldCz] as [number, number, number] };
  }, [points, frame]);

  if (!lines) return null;

  return (
    <group>
      <lineSegments geometry={lines.lineGeo}>
        <lineBasicMaterial color="#ffffff" linewidth={1.5} />
      </lineSegments>
      {/* Center circle */}
      <mesh position={lines.center} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[5.5, 5.6, 32]} />
        <meshBasicMaterial color="#ffffff" side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Structure Rendering Component
// --------------------------------------------------------------------------- //
function StructureMesh({
  structure,
  frame,
  palette,
  selected,
  onPick,
  viewMode,
}: {
  structure: StructureModel;
  frame: Frame;
  palette: Palette;
  selected: boolean;
  onPick: (t: PickTarget) => void;
  viewMode: ViewMode;
}) {
  const elevation = 0;
  const tiers = useMemo(() => structureTiers(structure, elevation), [structure]);
  const isWall = structure.type === 'WALL' || structure.type === 'COLUMN';
  const isSeating = structure.type === 'SEATING';
  const isField = structure.type === 'FIELD';

  const baseColor = useMemo(() => {
    if (viewMode === 'confidence') {
      const conf = Number(structure.metadata?.confidence ?? 0.9);
      return getConfidenceColor(conf);
    }
    return (
      STRUCTURE_COLOR[structure.type] ??
      (structure.type === 'ROOM'
        ? ROOM_KIND_COLOR[String(structure.metadata?.kind ?? '')] ?? '#5b6471'
        : palette.slabFront)
    );
  }, [structure, palette, viewMode]);

  const meshes = useMemo(() => {
    return tiers.map((t, i) => {
      const geo = extrudePolygon(t.points, t.depth, frame, t.elevation);
      const darken = isSeating ? i * 0.06 : 0;
      const color = new THREE.Color(baseColor).multiplyScalar(1 - darken);
      return { key: `${structure.id}-${i}`, geo, color, depth: t.depth, elevation: t.elevation };
    });
  }, [tiers, frame, structure.id, isSeating, baseColor]);

  // Wall caps
  const caps = useMemo(() => {
    if (!isWall || viewMode === 'simulation') return [];
    return tiers.map((t, i) => {
      const capGeo = extrudePolygon(t.points, 0.08, frame, t.elevation + t.depth);
      const color = new THREE.Color(baseColor).multiplyScalar(0.7); // Darker top cap
      return { key: `${structure.id}-cap-${i}`, geo: capGeo, color };
    });
  }, [isWall, tiers, frame, structure.id, baseColor, viewMode]);

  // Procedural seating rows
  const seatInstances = useMemo(() => {
    if (!isSeating || viewMode === 'simulation' || viewMode === 'confidence') return [];
    const accumulated: SeatInfo[] = [];
    tiers.forEach((t) => {
      accumulated.push(...generateSeatsForTier(t.points, t.elevation + t.depth, frame));
    });
    return accumulated;
  }, [isSeating, tiers, frame, viewMode]);

  // Reference for instanced seats
  const instancedSeatsRef = useRef<THREE.InstancedMesh>(null);
  useEffect(() => {
    const mesh = instancedSeatsRef.current;
    if (mesh && seatInstances.length > 0) {
      const dummy = new THREE.Object3D();
      seatInstances.forEach((seat, idx) => {
        dummy.position.set(...seat.pos);
        dummy.rotation.set(0, seat.rot, 0);
        dummy.updateMatrix();
        mesh.setMatrixAt(idx, dummy.matrix);
      });
      mesh.instanceMatrix.needsUpdate = true;
    }
  }, [seatInstances]);

  const matProps = useMemo(() => {
    let opacity = 1.0;
    let transparent = false;
    let emissive = selected ? palette.ok : '#000000';
    let emissiveIntensity = selected ? 0.35 : 0;

    if (viewMode === 'simulation') {
      opacity = 0.15;
      transparent = true;
    } else if (viewMode === 'circulation') {
      if (structure.type === 'CONCOURSE' || structure.type === 'STAIR' || structure.type === 'STAIRS') {
        emissive = palette.ok;
        emissiveIntensity = 0.25;
      }
    }
    return { opacity, transparent, emissive, emissiveIntensity };
  }, [viewMode, selected, palette, structure.type]);

  return (
    <group>
      {meshes.map(({ key, geo, color }) => (
        <mesh
          key={key}
          geometry={geo}
          castShadow
          receiveShadow
          onClick={(e) => {
            e.stopPropagation();
            onPick({ kind: 'structure', id: structure.id });
          }}
        >
          <meshStandardMaterial
            color={color}
            metalness={isWall ? 0.3 : 0.05}
            roughness={0.7}
            side={THREE.DoubleSide}
            transparent={matProps.transparent}
            opacity={matProps.opacity}
            emissive={matProps.emissive}
            emissiveIntensity={matProps.emissiveIntensity}
          />
        </mesh>
      ))}

      {/* Wall Top Caps */}
      {caps.map(({ key, geo, color }) => (
        <mesh key={key} geometry={geo} castShadow>
          <meshStandardMaterial color={color} roughness={0.4} metalness={0.5} />
        </mesh>
      ))}

      {/* Procedural Seating Pods */}
      {seatInstances.length > 0 && (
        <instancedMesh
          ref={instancedSeatsRef}
          args={[undefined, undefined, seatInstances.length]}
          castShadow
        >
          <boxGeometry args={[0.35, 0.3, 0.35]} />
          <meshStandardMaterial color="#b22b2b" roughness={0.8} />
        </instancedMesh>
      )}

      {/* Procedural Field Markings */}
      {isField && viewMode !== 'simulation' && (
        <FieldMarkings points={structure.polygon.points} frame={frame} />
      )}
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Path / Walkway Rendering Component
// --------------------------------------------------------------------------- //
function PathBand({
  path,
  frame,
  palette,
  selected,
  onPick,
  viewMode,
}: {
  path: PathGeometryModel;
  frame: Frame;
  palette: Palette;
  selected: boolean;
  onPick: (t: PickTarget) => void;
  viewMode: ViewMode;
}) {
  const geo = useMemo(
    () => bandGeometry(path.centerline, path.width_m ?? 3, frame, 0.18),
    [frame, path.centerline, path.width_m],
  );

  const matColor = useMemo(() => {
    if (viewMode === 'confidence') {
      const conf = Number(path.metadata?.confidence ?? 0.9);
      return getConfidenceColor(conf);
    }
    return palette.ink;
  }, [palette, viewMode, path]);

  // Side Kerbs / Boundaries
  const kerbsGeo = useMemo(() => {
    if (viewMode === 'simulation' || path.centerline.length < 2) return null;
    const half = (path.width_m ?? 3) / 2 + 0.1;
    const points: number[] = [];

    // Left and right kerb lines
    for (let i = 0; i < path.centerline.length - 1; i++) {
      const p1 = path.centerline[i];
      const p2 = path.centerline[i + 1];
      const dx = p2.x - p1.x;
      const dy = p2.y - p1.y;
      const len = Math.hypot(dx, dy) || 1;
      const nx = -dy / len;
      const ny = dx / len;

      const [wLx1, , wLz1] = frame.toWorld(p1.x + nx * half, p1.y + ny * half, 0.22);
      const [wLx2, , wLz2] = frame.toWorld(p2.x + nx * half, p2.y + ny * half, 0.22);
      const [wRx1, , wRz1] = frame.toWorld(p1.x - nx * half, p1.y - ny * half, 0.22);
      const [wRx2, , wRz2] = frame.toWorld(p2.x - nx * half, p2.y - ny * half, 0.22);

      points.push(wLx1, 0.22, wLz1, wLx2, 0.22, wLz2);
      points.push(wRx1, 0.22, wRz1, wRx2, 0.22, wRz2);
    }

    const kerbLinesGeo = new THREE.BufferGeometry();
    kerbLinesGeo.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
    return kerbLinesGeo;
  }, [path, frame, viewMode]);

  return (
    <group>
      <mesh
        geometry={geo}
        receiveShadow
        onClick={(e) => {
          e.stopPropagation();
          onPick({ kind: 'path', id: path.id });
        }}
      >
        <meshStandardMaterial
          color={matColor}
          transparent
          opacity={selected ? 0.9 : viewMode === 'circulation' ? 0.6 : 0.35}
          roughness={0.9}
          emissive={selected ? palette.ok : '#000000'}
          emissiveIntensity={selected ? 0.4 : 0}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      {/* Path Borders / Kerbs */}
      {kerbsGeo && (
        <lineSegments geometry={kerbsGeo}>
          <lineBasicMaterial color={palette.line} linewidth={2} />
        </lineSegments>
      )}
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Gate/Opening 3D Booth Component
// --------------------------------------------------------------------------- //
function OpeningMarker({
  opening,
  frame,
  palette,
  selected,
  onPick,
  viewMode,
  emergencyMode,
}: {
  opening: OpeningModel;
  frame: Frame;
  palette: Palette;
  selected: boolean;
  onPick: (t: PickTarget) => void;
  viewMode: ViewMode;
  emergencyMode: boolean;
}) {
  const [x, , z] = frame.toWorld(opening.position.x, opening.position.y);
  
  const color = useMemo(() => {
    if (viewMode === 'confidence') {
      const conf = Number(opening.metadata?.confidence ?? 0.9);
      return getConfidenceColor(conf);
    }
    return OPENING_COLOR[opening.type] ?? palette.warn;
  }, [opening, palette, viewMode]);

  const width = Math.max(2, Math.min(20, opening.width_m ?? 4));
  const rotY = ((opening.rotation_deg ?? 0) * Math.PI) / 180;
  const [hovered, setHovered] = useState(false);
  const arrowRef = useRef<THREE.Group>(null);

  // Chevron floating bobbing & pulse
  useFrame(({ clock }) => {
    if (arrowRef.current) {
      arrowRef.current.position.y = 4.2 + Math.sin(clock.getElapsedTime() * 4) * 0.25;
      arrowRef.current.rotation.y = clock.getElapsedTime() * 1.5;
    }
  });

  return (
    <group position={[x, 0, z]}>
      {/* clickable interaction layer */}
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, 0.05, 0]}
        onClick={(e) => {
          e.stopPropagation();
          onPick({ kind: 'opening', id: opening.id });
        }}
        onPointerOver={(e) => {
          e.stopPropagation();
          setHovered(true);
        }}
        onPointerOut={() => setHovered(false)}
      >
        <ringGeometry args={[width / 2 - 0.4, width / 2 + 0.6, 32]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={selected || hovered ? 1 : 0.6}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      {/* 3D Gate Structural Booth */}
      <group rotation={[0, rotY, 0]}>
        {/* Canopy ceiling */}
        <mesh position={[0, 3.2, 0]}>
          <boxGeometry args={[width + 0.5, 0.25, 1.8]} />
          <meshStandardMaterial color="#2d333b" metalness={0.8} roughness={0.2} />
        </mesh>
        
        {/* Structural Side Pillars */}
        <mesh position={[-width / 2, 1.6, 0]}>
          <cylinderGeometry args={[0.1, 0.1, 3.2, 8]} />
          <meshStandardMaterial color="#7c8794" metalness={0.7} roughness={0.3} />
        </mesh>
        <mesh position={[width / 2, 1.6, 0]}>
          <cylinderGeometry args={[0.1, 0.1, 3.2, 8]} />
          <meshStandardMaterial color="#7c8794" metalness={0.7} roughness={0.3} />
        </mesh>

        {/* Turnstile blocks */}
        {width >= 3 && (
          <>
            <mesh position={[-width / 4, 0.6, 0]}>
              <boxGeometry args={[0.6, 1.2, 0.6]} />
              <meshStandardMaterial color="#4f5660" metalness={0.6} roughness={0.4} />
            </mesh>
            <mesh position={[width / 4, 0.6, 0]}>
              <boxGeometry args={[0.6, 1.2, 0.6]} />
              <meshStandardMaterial color="#4f5660" metalness={0.6} roughness={0.4} />
            </mesh>
          </>
        )}

        {/* Center gate bar */}
        <mesh position={[0, 1.2, 0]}>
          <boxGeometry args={[width - 0.4, 0.15, 0.15]} />
          <meshStandardMaterial
            color={color}
            emissive={selected ? palette.ok : color}
            emissiveIntensity={selected ? 0.75 : 0.15}
          />
        </mesh>
      </group>

      {/* Floating flow direction indicator arrow */}
      <group ref={arrowRef} position={[0, 4.2, 0]}>
        <mesh rotation={[0, 0, 0]}>
          <coneGeometry args={[0.3, 0.7, 4]} />
          <meshBasicMaterial
            color={color}
            transparent
            opacity={0.85}
          />
        </mesh>
      </group>

      {/* Evac mode indicator overlay */}
      {emergencyMode && opening.is_emergency && (
        <pointLight position={[0, 3.6, 0]} color="#ca332b" intensity={2.0} distance={8} />
      )}

      {/* Label */}
      <Html position={[0, 5.4, 0]} center distanceFactor={15} style={{ pointerEvents: 'none' }}>
        <div
          className="whitespace-nowrap text-[10px] font-bold uppercase tracking-[0.18em]"
          style={{
            color: selected ? palette.ok : color,
            textShadow: '0 1px 3px rgba(0,0,0,0.85)',
            fontFamily: 'ui-monospace, monospace',
          }}
        >
          {opening.id.replace(/_/g, ' ')}
        </div>
      </Html>
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Navigation Graph 3D Overlay
// --------------------------------------------------------------------------- //
function NavigationGraphOverlay({
  nodes,
  edges,
  frame,
}: {
  nodes: any[];
  edges: any[];
  frame: Frame;
}) {
  const lineGeo = useMemo(() => {
    const points: number[] = [];
    edges.forEach((edge) => {
      const srcNode = nodes.find((n) => n.id === edge.source);
      const dstNode = nodes.find((n) => n.id === edge.destination);
      if (srcNode && dstNode) {
        const [wx1, , wz1] = frame.toWorld(srcNode.position.x, srcNode.position.y, 0.4);
        const [wx2, , wz2] = frame.toWorld(dstNode.position.x, dstNode.position.y, 0.4);
        points.push(wx1, 0.4, wz1, wx2, 0.4, wz2);
      }
    });

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
    return geo;
  }, [nodes, edges, frame]);

  return (
    <group>
      {/* Draw Nodes */}
      {nodes.map((node) => {
        const [nx, , nz] = frame.toWorld(node.position.x, node.position.y, 0.5);
        let color = '#2196f3';
        if (node.type === 'ENTRY') color = '#2e7d32';
        else if (node.type === 'EXIT' || node.type === 'EMERGENCY_EXIT') color = '#c62828';
        else if (node.type === 'CHECKPOINT') color = '#ef6c00';

        return (
          <mesh key={node.id} position={[nx, 0.5, nz]}>
            <octahedronGeometry args={[0.45]} />
            <meshBasicMaterial color={color} wireframe={false} />
          </mesh>
        );
      })}

      {/* Draw Edges */}
      <lineSegments geometry={lineGeo}>
        <lineBasicMaterial color="#ffeb3b" linewidth={2.5} opacity={0.8} transparent />
      </lineSegments>
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Crowd agents overlay
// --------------------------------------------------------------------------- //
function CrowdAgentsOverlay({
  agents,
  frame,
  palette,
}: {
  agents: AgentModel[];
  frame: Frame;
  palette: Palette;
}) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);

  useFrame(({ clock }) => {
    const mesh = meshRef.current;
    if (!mesh || agents.length === 0) return;
    const time = clock.getElapsedTime();
    agents.forEach((agent, i) => {
      // Bobbing animation based on speed
      const bob = agent.speed_mps > 0 ? Math.sin(time * agent.speed_mps * 8) * 0.12 : 0;
      const [wx, wy, wz] = frame.toWorld(agent.position.x, agent.position.y, 0.9 + bob);
      dummy.position.set(wx, wy, wz);
      dummy.scale.set(1.0, 1.0, 1.0);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
      
      const col = new THREE.Color(
        agent.is_emergency ? palette.danger : agent.is_rerouted ? palette.warn : palette.ok
      );
      mesh.setColorAt(i, col);
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });

  if (agents.length === 0) return null;
  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, agents.length]} castShadow>
      <capsuleGeometry args={[0.25, 0.8, 4, 8]} />
      <meshStandardMaterial vertexColors roughness={0.5} metalness={0.2} />
    </instancedMesh>
  );
}

// --------------------------------------------------------------------------- //
//  Level structures grouping
// --------------------------------------------------------------------------- //
function LevelStructures({
  level,
  frame,
  palette,
  structures,
  paths,
  openings,
  emergencyMode,
  selected,
  onPick,
  viewMode,
}: {
  level: LevelModel;
  frame: Frame;
  palette: Palette;
  structures: StructureModel[];
  paths: PathGeometryModel[];
  openings: OpeningModel[];
  emergencyMode: boolean;
  selected: PickTarget | null;
  onPick: (t: PickTarget) => void;
  viewMode: ViewMode;
}) {
  return (
    <group position={[0, level.elevation_m ?? 0, 0]}>
      {structures.map((s) => (
        <StructureMesh
          key={s.id}
          structure={s}
          frame={frame}
          palette={palette}
          selected={selected?.kind === 'structure' && selected.id === s.id}
          onPick={onPick}
          viewMode={viewMode}
        />
      ))}
      {paths.map((p) => {
        const isEmg = p.metadata?.is_emergency === true || p.metadata?.path_type === 'VOMITORY';
        if (emergencyMode && !isEmg) return null;
        return (
          <PathBand
            key={p.id}
            path={p}
            frame={frame}
            palette={palette}
            selected={selected?.kind === 'path' && selected.id === p.id}
            onPick={onPick}
            viewMode={viewMode}
          />
        );
      })}
      {openings.map((o) => (
        <OpeningMarker
          key={o.id}
          opening={o}
          frame={frame}
          palette={palette}
          selected={selected?.kind === 'opening' && selected.id === o.id}
          onPick={onPick}
          viewMode={viewMode}
          emergencyMode={emergencyMode}
        />
      ))}
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Venue Scene wrapper
// --------------------------------------------------------------------------- //
function VenueScene({
  spatial,
  width,
  height,
  palette,
  selected,
  onPick,
  activeLevelId,
  agents,
  emergencyMode,
  viewMode,
  navigationGraph,
}: {
  spatial: VenueSpatialModel;
  width: number;
  height: number;
  palette: Palette;
  selected: PickTarget | null;
  onPick: (t: PickTarget | null) => void;
  activeLevelId: string | null;
  agents: AgentModel[];
  emergencyMode: boolean;
  viewMode: ViewMode;
  navigationGraph: { nodes: any[]; edges: any[] } | null;
}) {
  const frame = useMemo(() => makeFrame(width, height), [width, height]);
  
  const byLevel = useMemo(() => {
    const map = new Map<
      string,
      { structures: StructureModel[]; paths: PathGeometryModel[]; openings: OpeningModel[] }
    >();
    for (const s of spatial.structures) {
      const entry = map.get(s.level_id) ?? { structures: [], paths: [], openings: [] };
      entry.structures.push(s);
      map.set(s.level_id, entry);
    }
    for (const p of spatial.paths) {
      const entry = map.get(p.level_id) ?? { structures: [], paths: [], openings: [] };
      entry.paths.push(p);
      map.set(p.level_id, entry);
    }
    for (const o of spatial.openings) {
      const entry = map.get(o.level_id) ?? { structures: [], paths: [], openings: [] };
      entry.openings.push(o);
      map.set(o.level_id, entry);
    }
    return map;
  }, [spatial]);

  const visibleLevels = activeLevelId
    ? spatial.levels.filter((lv) => lv.id === activeLevelId)
    : spatial.levels;

  return (
    <group>
      <Grid
        position={[0, 0.02, 0]}
        infiniteGrid
        cellSize={width / 20}
        sectionSize={width / 4}
        cellThickness={0.35}
        sectionThickness={0.9}
        cellColor={palette.line}
        sectionColor={palette.muted}
        fadeDistance={width * 3}
        fadeStrength={2.2}
      />

      {visibleLevels.map((level) => (
        <LevelStructures
          key={level.id}
          level={level}
          frame={frame}
          palette={palette}
          structures={byLevel.get(level.id)?.structures ?? []}
          paths={byLevel.get(level.id)?.paths ?? []}
          openings={byLevel.get(level.id)?.openings ?? []}
          emergencyMode={emergencyMode}
          selected={selected}
          onPick={onPick}
          viewMode={viewMode}
        />
      ))}

      {/* Navigation Graph Layer */}
      {viewMode === 'simulation' && navigationGraph && (
        <NavigationGraphOverlay
          nodes={navigationGraph.nodes}
          edges={navigationGraph.edges}
          frame={frame}
        />
      )}

      {/* Crowd agent overlay */}
      <CrowdAgentsOverlay agents={agents} frame={frame} palette={palette} />
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Selection Inspector Details
// --------------------------------------------------------------------------- //
function selectionDetails(
  selected: PickTarget,
  spatial: VenueSpatialModel,
): { title: string; rows: [string, string][] } | null {
  if (selected.kind === 'structure') {
    const s = spatial.structures.find((x) => x.id === selected.id);
    if (!s) return null;
    const xs = s.polygon.points.map((p) => p.x);
    const ys = s.polygon.points.map((p) => p.y);
    const rows: [string, string][] = [
      ['kind', s.type],
      ['extent', `${(Math.max(...xs) - Math.min(...xs)).toFixed(1)} × ${(Math.max(...ys) - Math.min(...ys)).toFixed(1)} m`],
      ['height', `${s.height_m ?? 2.0} m`],
      ['level', s.level_id],
      ['confidence', `${(Number(s.metadata?.confidence ?? 0.9) * 100).toFixed(0)}%`],
    ];
    for (const [k, v] of Object.entries(s.metadata ?? {})) {
      if (k !== 'confidence') rows.push([k.toLowerCase(), String(v)]);
    }
    return { title: s.id.replace(/_/g, ' '), rows };
  }
  if (selected.kind === 'opening') {
    const o = spatial.openings.find((x) => x.id === selected.id);
    if (!o) return null;
    const rows: [string, string][] = [
      ['type', o.type],
      ['width', `${o.width_m ?? 4} m`],
      ['rotation', `${o.rotation_deg ?? 0}°`],
      ['level', o.level_id],
      ['confidence', `${(Number(o.metadata?.confidence ?? 0.9) * 100).toFixed(0)}%`],
    ];
    for (const [k, v] of Object.entries(o.metadata ?? {})) {
      if (k !== 'confidence') rows.push([k.toLowerCase(), String(v)]);
    }
    return { title: o.id.replace(/_/g, ' '), rows };
  }
  const p = spatial.paths.find((x) => x.id === selected.id);
  if (!p) return null;
  const rows: [string, string][] = [
    ['points', `${p.centerline.length}`],
    ['width', `${p.width_m ?? 3} m`],
    ['length', `${p.centerline.reduce((acc, pt, i) => (i === 0 ? acc : acc + Math.hypot(pt.x - p.centerline[i - 1].x, pt.y - p.centerline[i - 1].y)), 0).toFixed(1)} m`],
    ['level', p.level_id],
    ['confidence', `${(Number(p.metadata?.confidence ?? 0.9) * 100).toFixed(0)}%`],
  ];
  for (const [k, v] of Object.entries(p.metadata ?? {})) {
    if (k !== 'confidence') rows.push([k.toLowerCase(), String(v)]);
  }
  return { title: p.id.replace(/_/g, ' '), rows };
}

// --------------------------------------------------------------------------- //
//  Main Component View
// --------------------------------------------------------------------------- //
export default function Venue3DView() {
  const { venue, theme, sim } = useSimulation();
  const palette = usePalette();
  const [spatial, setSpatial] = useState<VenueSpatialModel | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<PickTarget | null>(null);
  
  // Custom Visualization State
  const [viewMode, setViewMode] = useState<ViewMode>('architectural');
  const [activeLevelId, setActiveLevelId] = useState<string | null>(null);
  const [showAgents, setShowAgents] = useState(false);
  const [emergencyMode, setEmergencyMode] = useState(false);
  const [debugPlan, setDebugPlan] = useState(false);
  const [savingTwin, setSavingTwin] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Simulation agents state
  const agents: AgentModel[] = useMemo(() => {
    if (!showAgents || !sim) return [];
    return sim.agents ?? [];
  }, [showAgents, sim]);

  // Construct mock Navigation Graph from Venue data
  const navigationGraph = useMemo(() => {
    if (!venue) return null;
    return {
      nodes: venue.nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
      })),
      edges: venue.edges.map((e) => ({
        source: e.source,
        destination: e.destination,
        is_open: e.is_open,
      })),
    };
  }, [venue]);

  const load = useCallback(async (id: string) => {
    setSpatial(null);
    setActiveLevelId(null);
    setLoading(true);
    setError(null);
    try {
      const s = await api.venueSpatial(id);
      if (s && s.venue_id === id) {
        setSpatial(s);
      } else if (s && !s.venue_id) {
        setSpatial(s);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load spatial twin model');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (venue) void load(venue.id);
  }, [venue, load]);

  // Handle Editing Changes Locally
  const handleUpdateField = useCallback(
    (field: string, val: any) => {
      if (!selected || !spatial) return;
      setSpatial((prev) => {
        if (!prev) return null;
        const updated = { ...prev };
        
        if (selected.kind === 'structure') {
          updated.structures = prev.structures.map((s) => {
            if (s.id !== selected.id) return s;
            
            if (field === 'height_m') {
              return { ...s, height_m: Number(val) };
            }
            if (field === 'type') {
              return { ...s, type: val as StructureType };
            }
            if (field === 'confidence') {
              return { ...s, metadata: { ...s.metadata, confidence: Number(val) } };
            }
            if (field === 'translateX' || field === 'translateY') {
              const dx = field === 'translateX' ? Number(val) : 0;
              const dy = field === 'translateY' ? Number(val) : 0;
              return {
                ...s,
                polygon: {
                  points: s.polygon.points.map((p) => ({ x: p.x + dx, y: p.y + dy })),
                },
              };
            }
            return s;
          });
        } else if (selected.kind === 'opening') {
          updated.openings = prev.openings.map((o) => {
            if (o.id !== selected.id) return o;
            
            if (field === 'width_m') {
              return { ...o, width_m: Number(val) };
            }
            if (field === 'rotation_deg') {
              return { ...o, rotation_deg: Number(val) };
            }
            if (field === 'confidence') {
              return { ...o, metadata: { ...o.metadata, confidence: Number(val) } };
            }
            if (field === 'positionX') {
              return { ...o, position: { ...o.position, x: Number(val) } };
            }
            if (field === 'positionY') {
              return { ...o, position: { ...o.position, y: Number(val) } };
            }
            return o;
          });
        } else if (selected.kind === 'path') {
          updated.paths = prev.paths.map((p) => {
            if (p.id !== selected.id) return p;
            
            if (field === 'width_m') {
              return { ...p, width_m: Number(val) };
            }
            if (field === 'confidence') {
              return { ...p, metadata: { ...p.metadata, confidence: Number(val) } };
            }
            return p;
          });
        }
        return updated;
      });
    },
    [selected, spatial],
  );

  // Save changes via API
  const saveSpatialTwin = useCallback(async () => {
    if (!venue || !spatial) return;
    setSavingTwin(true);
    setSaveSuccess(false);
    try {
      await api.saveVenueSpatial(venue.id, spatial);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save spatial twin failed');
    } finally {
      setSavingTwin(false);
    }
  }, [venue, spatial]);

  if (!venue) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-od-canvas">
        <span className="text-[11px] uppercase tracking-[0.24em] text-od-muted">Select a venue first</span>
      </div>
    );
  }

  const inspector = selected && spatial ? selectionDetails(selected, spatial) : null;

  // Retrieve current active item model
  const activeItem = useMemo(() => {
    if (!selected || !spatial) return null;
    if (selected.kind === 'structure') {
      return spatial.structures.find((x) => x.id === selected.id) || null;
    }
    if (selected.kind === 'opening') {
      return spatial.openings.find((x) => x.id === selected.id) || null;
    }
    return spatial.paths.find((x) => x.id === selected.id) || null;
  }, [selected, spatial]);

  return (
    <div className="relative flex h-full w-full flex-col bg-od-canvas">
      {/* header strip */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-od-line bg-od-panel px-4 py-2">
        <span className="flex items-center gap-2 text-[10px] uppercase tracking-[0.16em] font-bold text-od-ink">
          <Box className="h-3.5 w-3.5" />
          {venue.name}
        </span>
        <span className="chip">
          <span className={`status-dot ${loading ? 'is-scan' : spatial ? 'is-ok' : 'is-danger'}`} />
          {loading ? 'LOADING SPATIAL' : spatial ? 'SPATIAL TWIN' : 'NO SPATIAL'}
        </span>

        {/* View Mode Selectors */}
        {spatial && (
          <div className="flex items-center gap-1 border-l border-r border-od-line px-2">
            <span className="text-[9px] uppercase tracking-[0.14em] text-od-muted mr-1.5 flex items-center gap-1">
              <Eye className="w-3 h-3" /> View Mode:
            </span>
            {(['architectural', 'circulation', 'simulation', 'confidence'] as ViewMode[]).map((mode) => (
              <button
                key={mode}
                onClick={() => setViewMode(mode)}
                className={`px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.1em] border transition-all ${
                  viewMode === mode
                    ? 'border-od-ink bg-od-ink text-od-bg'
                    : 'border-od-line text-od-muted hover:text-od-ink'
                }`}
              >
                {mode.substring(0, 4)}
              </button>
            ))}
          </div>
        )}

        {/* Level selector */}
        {spatial && spatial.levels.length > 1 && (
          <div className="flex items-center gap-1">
            <Layers className="h-3 w-3 text-od-muted" />
            <select
              value={activeLevelId ?? ''}
              onChange={(e) => setActiveLevelId(e.target.value || null)}
              className="border border-od-line bg-od-panel px-1.5 py-0.5 text-[9px] uppercase tracking-[0.14em] text-od-ink"
              aria-label="Select level"
            >
              <option value="">All levels</option>
              {spatial.levels.map((lv) => (
                <option key={lv.id} value={lv.id}>{lv.name}</option>
              ))}
            </select>
          </div>
        )}

        <span className="flex-1" />

        {/* Save Twin Button */}
        {spatial && (
          <button
            onClick={saveSpatialTwin}
            disabled={savingTwin}
            className={`btn btn-solid flex items-center gap-1 ${saveSuccess ? '!bg-od-ok text-white' : ''}`}
            title="Save updated Spatial Twin config"
          >
            {saveSuccess ? (
              <>
                <CheckCircle className="h-3.5 w-3.5 animate-bounce" />
                SAVED
              </>
            ) : (
              <>
                <Save className="h-3.5 w-3.5" />
                {savingTwin ? 'SAVING...' : 'SAVE TWIN'}
              </>
            )}
          </button>
        )}

        {/* Simulation agents toggle */}
        {sim && (
          <button
            onClick={() => setShowAgents((v) => !v)}
            className={`btn btn-ghost ${showAgents ? 'text-od-ok' : ''}`}
            title="Toggle crowd agent overlay"
            id="btn-toggle-agents"
          >
            <Activity className="h-3.5 w-3.5" />
            {showAgents ? 'AGENTS ON' : 'AGENTS'}
          </button>
        )}

        {/* Emergency mode */}
        <button
          onClick={() => setEmergencyMode((v) => !v)}
          className={`btn btn-ghost ${emergencyMode ? 'text-od-danger' : ''}`}
          title="Toggle emergency route highlight mode"
          id="btn-emergency-mode"
        >
          <Shield className="h-3.5 w-3.5" />
          {emergencyMode ? 'EVAC' : 'EVAC'}
        </button>

        <button
          onClick={() => setDebugPlan((v) => !v)}
          className="btn btn-ghost"
          title="Toggle the 2D plan canvas (debug view)"
          id="btn-toggle-plan"
        >
          {debugPlan ? <Box className="h-3.5 w-3.5" /> : <PanelsTopLeft className="h-3.5 w-3.5" />}
          {debugPlan ? '3D' : 'PLAN'}
        </button>
        <button
          onClick={() => venue && load(venue.id)}
          disabled={loading}
          className="btn btn-ghost"
          title="Reload the spatial model"
          id="btn-reload-spatial"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* body */}
      <div className="min-h-0 flex-1">
        {error ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
            <TriangleAlert className="h-5 w-5 text-od-danger" />
            <span className="text-[11px] uppercase tracking-[0.16em] text-od-muted">{error}</span>
            <button onClick={() => venue && load(venue.id)} className="btn btn-solid">
              Retry
            </button>
          </div>
        ) : loading && !spatial ? (
          <div className="flex h-full items-center justify-center">
            <span className="text-[10px] uppercase tracking-[0.24em] text-od-muted">Loading spatial model…</span>
          </div>
        ) : !spatial ? (
          <div className="flex h-full items-center justify-center">
            <span className="text-[10px] uppercase tracking-[0.24em] text-od-muted">No spatial model available</span>
          </div>
        ) : debugPlan ? (
          <InstrumentCanvas
            venue={venue}
            sim={null}
            mode="simulate"
            selected={null}
            interactive={false}
            showAgents={false}
          />
        ) : (
          <div className="relative h-full w-full">
            <Canvas
              shadows
              dpr={[1, 2]}
              camera={{
                position: [venue.width * 0.9, venue.height * 1.1, venue.height * 1.35],
                fov: 38,
                near: 0.5,
                far: venue.width * 20,
              }}
              onPointerMissed={() => setSelected(null)}
            >
              <color attach="background" args={[palette.canvas]} />
              <fog attach="fog" args={[palette.canvas, venue.width * 1.1, venue.width * 3.2]} />
              <ambientLight intensity={theme === 'dark' ? 0.65 : 0.9} />
              <directionalLight
                position={[venue.width * 0.6, venue.height, venue.height * 0.5]}
                intensity={1.6}
                castShadow
              />
              <directionalLight
                position={[-venue.width * 0.4, venue.height * 0.4, -venue.height * 0.5]}
                intensity={0.5}
              />
              <Suspense fallback={null}>
                <VenueScene
                  spatial={spatial}
                  width={venue.width}
                  height={venue.height}
                  palette={palette}
                  selected={selected}
                  onPick={setSelected}
                  activeLevelId={activeLevelId}
                  agents={agents}
                  emergencyMode={emergencyMode}
                  viewMode={viewMode}
                  navigationGraph={navigationGraph}
                />
              </Suspense>
              <OrbitControls
                makeDefault
                target={[0, 4, 0]}
                enableDamping
                dampingFactor={0.08}
                minDistance={venue.width * 0.12}
                maxDistance={venue.width * 4}
                maxPolarAngle={Math.PI / 2.05}
              />
            </Canvas>

            {/* Hint */}
            <div className="pointer-events-none absolute bottom-2 left-2 flex items-center gap-2 border border-od-line bg-od-panel/90 px-2 py-1 text-[9px] uppercase tracking-[0.14em] text-od-muted">
              <Camera className="h-3 w-3" />
              drag orbit · scroll zoom · click to inspect
              {emergencyMode && <span className="text-od-danger font-bold">— EVAC ACTIVE</span>}
            </div>

            {/* Selection Inspector & Editor */}
            {selected && inspector && activeItem && (
              <div className="absolute top-2 left-2 z-10 w-72 max-w-[calc(100%-1rem)] border border-od-line bg-od-panel shadow-md flex flex-col max-h-[90%] overflow-y-auto scrollbar-thin">
                <div className="flex items-center justify-between border-b border-od-line px-3 py-2">
                  <span className="truncate text-[10px] uppercase tracking-[0.16em] font-bold text-od-ink">
                    {inspector.title}
                  </span>
                  <button
                    onClick={() => setSelected(null)}
                    aria-label="Close inspector"
                    className="cursor-pointer px-1 text-od-muted hover:text-od-ink"
                  >
                    ✕
                  </button>
                </div>

                {/* Properties list */}
                <dl className="space-y-1 px-3 py-2 border-b border-od-line">
                  {inspector.rows.map(([k, v]) => (
                    <div
                      key={k}
                      className="flex items-baseline justify-between gap-2 text-[9px] uppercase tracking-[0.12em]"
                    >
                      <dt className="text-od-muted">{k}</dt>
                      <dd className="truncate font-bold text-od-ink mono-tabular">{v}</dd>
                    </div>
                  ))}
                </dl>

                {/* Digital Twin Spatial Editor */}
                <div className="px-3 py-3 space-y-3 bg-od-surface">
                  <span className="text-[9px] uppercase tracking-[0.18em] font-bold text-od-muted flex items-center gap-1.5">
                    <Sliders className="w-3.5 h-3.5" /> Modify Digital Twin
                  </span>

                  {/* Width edit (structure, path, opening) */}
                  {(selected.kind === 'path' || selected.kind === 'opening') && (
                    <label className="block space-y-1">
                      <span className="text-[8px] uppercase tracking-[0.1em] text-od-muted">Width (m)</span>
                      <input
                        type="number"
                        step="0.5"
                        min="0.5"
                        max="25"
                        value={(activeItem as any).width_m ?? 3}
                        onChange={(e) => handleUpdateField('width_m', e.target.value)}
                        className="field w-full text-[10px] font-bold mono-tabular"
                      />
                    </label>
                  )}

                  {/* Height edit (structure) */}
                  {selected.kind === 'structure' && (
                    <label className="block space-y-1">
                      <span className="text-[8px] uppercase tracking-[0.1em] text-od-muted">Height (m)</span>
                      <input
                        type="number"
                        step="0.5"
                        min="0.1"
                        max="30"
                        value={(activeItem as any).height_m ?? 2}
                        onChange={(e) => handleUpdateField('height_m', e.target.value)}
                        className="field w-full text-[10px] font-bold mono-tabular"
                      />
                    </label>
                  )}

                  {/* Position translate X/Y (structure) */}
                  {selected.kind === 'structure' && (
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        onClick={() => handleUpdateField('translateX', -1)}
                        className="btn btn-ghost text-[8px] border border-od-line"
                      >
                        Shift -X
                      </button>
                      <button
                        onClick={() => handleUpdateField('translateX', 1)}
                        className="btn btn-ghost text-[8px] border border-od-line"
                      >
                        Shift +X
                      </button>
                      <button
                        onClick={() => handleUpdateField('translateY', -1)}
                        className="btn btn-ghost text-[8px] border border-od-line"
                      >
                        Shift -Y
                      </button>
                      <button
                        onClick={() => handleUpdateField('translateY', 1)}
                        className="btn btn-ghost text-[8px] border border-od-line"
                      >
                        Shift +Y
                      </button>
                    </div>
                  )}

                  {/* Position X/Y (opening) */}
                  {selected.kind === 'opening' && (
                    <div className="grid grid-cols-2 gap-2">
                      <label className="block space-y-1">
                        <span className="text-[8px] uppercase tracking-[0.1em] text-od-muted">Position X</span>
                        <input
                          type="number"
                          value={(activeItem as any).position?.x ?? 0}
                          onChange={(e) => handleUpdateField('positionX', e.target.value)}
                          className="field w-full text-[10px] font-bold mono-tabular"
                        />
                      </label>
                      <label className="block space-y-1">
                        <span className="text-[8px] uppercase tracking-[0.1em] text-od-muted">Position Y</span>
                        <input
                          type="number"
                          value={(activeItem as any).position?.y ?? 0}
                          onChange={(e) => handleUpdateField('positionY', e.target.value)}
                          className="field w-full text-[10px] font-bold mono-tabular"
                        />
                      </label>
                    </div>
                  )}

                  {/* Rotation (opening) */}
                  {selected.kind === 'opening' && (
                    <label className="block space-y-1">
                      <span className="text-[8px] uppercase tracking-[0.1em] text-od-muted">Rotation (deg)</span>
                      <input
                        type="number"
                        step="5"
                        value={(activeItem as any).rotation_deg ?? 0}
                        onChange={(e) => handleUpdateField('rotation_deg', e.target.value)}
                        className="field w-full text-[10px] font-bold mono-tabular"
                      />
                    </label>
                  )}

                  {/* AI Confidence Edit */}
                  <label className="block space-y-1">
                    <span className="text-[8px] uppercase tracking-[0.1em] text-od-muted">AI Confidence (0.0 - 1.0)</span>
                    <input
                      type="number"
                      step="0.05"
                      min="0.1"
                      max="1.0"
                      value={(activeItem as any).metadata?.confidence ?? 0.9}
                      onChange={(e) => handleUpdateField('confidence', e.target.value)}
                      className="field w-full text-[10px] font-bold mono-tabular"
                    />
                  </label>
                </div>
              </div>
            )}

            {/* Legend */}
            <div className="pointer-events-none absolute bottom-2 right-2 hidden items-center gap-x-3 gap-y-1 border border-od-line bg-od-panel/90 px-2 py-1 text-[9px] uppercase tracking-[0.14em] text-od-muted md:flex">
              {(
                [
                  ['ENTRY', palette.ok],
                  ['EXIT', palette.warn],
                  ['EMERGENCY', palette.danger],
                ] as [string, string][]
              ).map(([label, color]) => (
                <span key={label} className="inline-flex items-center gap-1.5">
                  <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
                  {label.toLowerCase()}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
