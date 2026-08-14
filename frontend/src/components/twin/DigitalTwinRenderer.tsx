import { Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Html, OrbitControls, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import {
  TWIN_PALETTE,
  OPENING_COLOR,
  ROOM_KIND_COLOR,
  STRUCTURE_COLOR,
  applyAgents,
  bandGeometry,
  extrudePolygon,
  generateSeatsForTier,
  makeFrame,
  structureTiers,
  type Frame,
  type TwinPalette,
} from './twinGeometry';
import type {
  AgentModel,
  Bottleneck,
  LevelModel,
  OpeningModel,
  PathGeometryModel,
  Point2D,
  SimulationState,
  StructureModel,
  VenueModel,
  VenueSpatialModel,
} from '../../lib/types';

export type TwinPick = { kind: 'structure' | 'opening' | 'path'; id: string };
export type CameraPreset = 'overview' | 'focus' | 'follow' | 'ground';

export interface TwinProps {
  venue: VenueModel;
  spatial: VenueSpatialModel;
  sim: SimulationState | null;
  simRef: React.RefObject<SimulationState | null>;
  mode: 'live' | 'predict' | 'whatif' | 'optimize';
  compareSim: SimulationState | null;
  compareSide: 'baseline' | 'whatif';
  bottlenecks: Bottleneck[];
  selected: TwinPick | null;
  onPick: (t: TwinPick | null) => void;
  cameraPreset: CameraPreset;
  onCameraPresetChange: (p: CameraPreset) => void;
  onBottleneckSelect: (b: Bottleneck) => void;
  /** URL of a generated venue.glb (AI / procedural 3D twin). When present the
   *  GLB becomes the venue shell; gates, crowd and congestion stay procedural.
   *  glbMode 'world' means the GLB is already in the twin world frame
   *  (procedural / simulated). 'auto' means it is a raw AI mesh with arbitrary
   *  scale/orientation — it is auto-fitted to the venue footprint and the
   *  procedural structures stay visible as a ghost underneath. */
  glbUrl?: string | null;
  glbMode?: 'world' | 'auto';
}

function riskColor(risk: string, palette: TwinPalette): string {
  if (risk === 'CRITICAL') return palette.danger;
  if (risk === 'ELEVATED') return palette.warn;
  return palette.ok;
}

// --------------------------------------------------------------------------- //
//  Field markings (grass pitch lines)
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
    const vertices: number[] = [];
    const addSeg = (x1: number, y1: number, x2: number, y2: number) => {
      const [wx1, , wz1] = frame.toWorld(x1, y1, 0.06);
      const [wx2, , wz2] = frame.toWorld(x2, y2, 0.06);
      vertices.push(wx1, 0.06, wz1, wx2, 0.06, wz2);
    };
    addSeg(minX + 1, minY + 1, maxX - 1, minY + 1);
    addSeg(maxX - 1, minY + 1, maxX - 1, maxY - 1);
    addSeg(maxX - 1, maxY - 1, minX + 1, maxY - 1);
    addSeg(minX + 1, maxY - 1, minX + 1, minY + 1);
    if (w > h) addSeg(cx, minY + 1, cx, maxY - 1);
    else addSeg(minX + 1, cy, maxX - 1, cy);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    const [wcX, , wcZ] = frame.toWorld(cx, cy, 0.06);
    return { geo, center: [wcX, 0.06, wcZ] as [number, number, number] };
  }, [points, frame]);
  if (!lines) return null;
  return (
    <group>
      <lineSegments geometry={lines.geo}>
        <lineBasicMaterial color="#d7dde3" linewidth={1.5} transparent opacity={0.7} />
      </lineSegments>
      <mesh position={lines.center} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[5.5, 5.6, 32]} />
        <meshBasicMaterial color="#d7dde3" side={THREE.DoubleSide} transparent opacity={0.7} />
      </mesh>
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Structure mesh (extruded slab / tiered stands / walls)
// --------------------------------------------------------------------------- //
function StructureMesh({
  structure,
  frame,
  palette,
  selected,
  onPick,
  live,
}: {
  structure: StructureModel;
  frame: Frame;
  palette: TwinPalette;
  selected: boolean;
  onPick: (t: TwinPick) => void;
  live: boolean;
}) {
  const elevation = 0;
  const tiers = useMemo(() => structureTiers(structure, elevation), [structure]);
  const isWall = structure.type === 'WALL' || structure.type === 'COLUMN';
  const isSeating = structure.type === 'SEATING';
  const isField = structure.type === 'FIELD';

  const baseColor = useMemo(
    () =>
      STRUCTURE_COLOR[structure.type] ??
      (structure.type === 'ROOM'
        ? ROOM_KIND_COLOR[String(structure.metadata?.kind ?? '')] ?? '#3a4350'
        : palette.slabFront),
    [structure, palette],
  );

  const meshes = useMemo(
    () =>
      tiers.map((t, i) => {
        const geo = extrudePolygon(t.points, t.depth, frame, t.elevation);
        const darken = isSeating ? i * 0.07 : 0;
        const color = new THREE.Color(baseColor).multiplyScalar(1 - darken);
        return { key: `${structure.id}-${i}`, geo, color };
      }),
    [tiers, frame, structure.id, isSeating, baseColor],
  );

  const caps = useMemo(() => {
    if (!isWall) return [];
    return tiers.map((t, i) => ({
      key: `${structure.id}-cap-${i}`,
      geo: extrudePolygon(t.points, 0.08, frame, t.elevation + t.depth),
      color: new THREE.Color(baseColor).multiplyScalar(0.6),
    }));
  }, [isWall, tiers, frame, structure.id, baseColor]);

  const seats = useMemo(() => {
    if (!isSeating) return [];
    const acc: ReturnType<typeof generateSeatsForTier> = [];
    tiers.forEach((t) => acc.push(...generateSeatsForTier(t.points, t.elevation + t.depth, frame)));
    return acc;
  }, [isSeating, tiers, frame]);

  const seatRef = useRef<THREE.InstancedMesh>(null);
  useEffect(() => {
    const mesh = seatRef.current;
    if (!mesh || !seats.length) return;
    const d = new THREE.Object3D();
    seats.forEach((s, i) => {
      d.position.set(...s.pos);
      d.rotation.set(0, s.rot, 0);
      d.updateMatrix();
      mesh.setMatrixAt(i, d.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
  }, [seats]);

  return (
    <group>
      {meshes.map(({ key, geo, color }) => (
        <mesh key={key} geometry={geo} castShadow receiveShadow onClick={(e) => { e.stopPropagation(); onPick({ kind: 'structure', id: structure.id }); }}>
          <meshStandardMaterial
            color={color}
            metalness={isWall ? 0.3 : 0.05}
            roughness={0.7}
            side={THREE.DoubleSide}
            transparent={!live && !isField}
            opacity={!live && !isField ? 0.18 : 1}
            emissive={selected ? palette.ok : '#000000'}
            emissiveIntensity={selected ? 0.4 : 0}
          />
        </mesh>
      ))}
      {caps.map(({ key, geo, color }) => (
        <mesh key={key} geometry={geo} castShadow>
          <meshStandardMaterial color={color} roughness={0.4} metalness={0.5} />
        </mesh>
      ))}
      {seats.length > 0 && (
        <instancedMesh ref={seatRef} args={[undefined, undefined, seats.length]} castShadow>
          <boxGeometry args={[0.35, 0.3, 0.35]} />
          <meshStandardMaterial color="#8a2f2f" roughness={0.8} />
        </instancedMesh>
      )}
      {isField && <FieldMarkings points={structure.polygon.points} frame={frame} />}
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Path / concourse band
// --------------------------------------------------------------------------- //
function PathBand({
  path,
  frame,
  palette,
  selected,
  onPick,
  congestion,
}: {
  path: PathGeometryModel;
  frame: Frame;
  palette: TwinPalette;
  selected: boolean;
  onPick: (t: TwinPick) => void;
  congestion: string | null;
}) {
  const geo = useMemo(() => bandGeometry(path.centerline, path.width_m ?? 3, frame, 0.18), [frame, path]);
  const color = congestion ? riskColor(congestion, palette) : palette.ink;
  return (
    <group>
      <mesh geometry={geo} receiveShadow onClick={(e) => { e.stopPropagation(); onPick({ kind: 'path', id: path.id }); }}>
        <meshStandardMaterial
          color={color}
          transparent
          opacity={congestion ? 0.55 : 0.35}
          roughness={0.9}
          emissive={congestion || selected ? color : '#000000'}
          emissiveIntensity={congestion ? 0.45 : selected ? 0.35 : 0}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Gate / opening booth
// --------------------------------------------------------------------------- //
function OpeningMarker({
  opening,
  frame,
  palette,
  selected,
  onPick,
  congestion,
}: {
  opening: OpeningModel;
  frame: Frame;
  palette: TwinPalette;
  selected: boolean;
  onPick: (t: TwinPick) => void;
  congestion: string | null;
}) {
  const [x, , z] = frame.toWorld(opening.position.x, opening.position.y);
  const color = congestion ? riskColor(congestion, palette) : OPENING_COLOR[opening.type] ?? palette.warn;
  const width = Math.max(2, Math.min(20, opening.width_m ?? 4));
  const rotY = ((opening.rotation_deg ?? 0) * Math.PI) / 180;
  const [hovered, setHovered] = useState(false);
  const arrowRef = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    if (arrowRef.current) {
      arrowRef.current.position.y = 4.4 + Math.sin(clock.getElapsedTime() * 4) * 0.25;
      arrowRef.current.rotation.y = clock.getElapsedTime() * 1.5;
    }
  });
  const picked = selected || hovered;
  return (
    <group position={[x, 0, z]}>
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, 0.05, 0]}
        onClick={(e) => { e.stopPropagation(); onPick({ kind: 'opening', id: opening.id }); }}
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
        onPointerOut={() => setHovered(false)}
      >
        <ringGeometry args={[width / 2 - 0.4, width / 2 + 0.6, 32]} />
        <meshBasicMaterial color={color} transparent opacity={picked ? 1 : 0.6} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
      <group rotation={[0, rotY, 0]}>
        <mesh position={[0, 3.2, 0]}>
          <boxGeometry args={[width + 0.5, 0.25, 1.8]} />
          <meshStandardMaterial color="#2d333b" metalness={0.8} roughness={0.2} />
        </mesh>
        <mesh position={[-width / 2, 1.6, 0]}>
          <cylinderGeometry args={[0.1, 0.1, 3.2, 8]} />
          <meshStandardMaterial color="#7c8794" metalness={0.7} roughness={0.3} />
        </mesh>
        <mesh position={[width / 2, 1.6, 0]}>
          <cylinderGeometry args={[0.1, 0.1, 3.2, 8]} />
          <meshStandardMaterial color="#7c8794" metalness={0.7} roughness={0.3} />
        </mesh>
        <mesh position={[0, 1.2, 0]}>
          <boxGeometry args={[width - 0.4, 0.15, 0.15]} />
          <meshStandardMaterial color={color} emissive={picked ? palette.ok : color} emissiveIntensity={picked ? 0.75 : 0.2} />
        </mesh>
      </group>
      <group ref={arrowRef} position={[0, 4.4, 0]}>
        <mesh>
          <coneGeometry args={[0.3, 0.7, 4]} />
          <meshBasicMaterial color={color} transparent opacity={0.85} />
        </mesh>
      </group>
      {opening.is_emergency && <pointLight position={[0, 3.6, 0]} color="#ef4444" intensity={1.6} distance={9} />}
      <Html position={[0, 5.6, 0]} center distanceFactor={15} style={{ pointerEvents: 'none' }}>
        <div
          className="whitespace-nowrap text-[9px] font-bold uppercase tracking-[0.16em] mono-tabular"
          style={{ color: picked ? palette.ok : color, textShadow: '0 1px 3px rgba(0,0,0,0.9)' }}
        >
          {opening.id.replace(/_/g, ' ')}
        </div>
      </Html>
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Instanced crowd — lives inside the twin, read from simRef each frame.
// --------------------------------------------------------------------------- //
function Crowd({
  agents,
  frame,
  palette,
  maxAgents,
}: {
  agents: AgentModel[];
  frame: Frame;
  palette: TwinPalette;
  maxAgents: number;
}) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const prevCount = useRef(maxAgents);
  useEffect(() => {
    if (prevCount.current !== maxAgents && meshRef.current) {
      meshRef.current.count = maxAgents;
      prevCount.current = maxAgents;
    }
  }, [maxAgents]);
  useFrame(({ clock }) => {
    applyAgents(meshRef.current, agents, frame, clock.getElapsedTime(), palette);
  });
  if (maxAgents <= 0) return null;
  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, maxAgents]} castShadow>
      <capsuleGeometry args={[0.28, 0.75, 4, 8]} />
      <meshStandardMaterial vertexColors roughness={0.5} metalness={0.25} />
    </instancedMesh>
  );
}

// --------------------------------------------------------------------------- //
//  Prediction volume — translucent projected congestion region over the twin.
// --------------------------------------------------------------------------- //
function PredictionVolume({
  bottleneck,
  spatial,
  frame,
  palette,
  onClick,
}: {
  bottleneck: Bottleneck;
  spatial: VenueSpatialModel;
  frame: Frame;
  palette: TwinPalette;
  onClick: () => void;
}) {
  const region = useMemo(() => {
    const loc = bottleneck.location;
    const opening = spatial.openings.find((o) => o.id === loc || o.id.replace(/_/g, '') === loc.replace(/[^A-Z0-9]/gi, ''));
    const path = spatial.paths.find((p) => p.id === loc);
    if (opening) {
      const [x, , z] = frame.toWorld(opening.position.x, opening.position.y, 1.5);
      const w = Math.max(6, opening.width_m ?? 6);
      return { kind: 'box', pos: [x, 1.5, z] as [number, number, number], size: [w * 2.4, 3.2, w * 1.6] as [number, number, number] };
    }
    if (path && path.centerline.length) {
      const c = path.centerline[Math.floor(path.centerline.length / 2)];
      const [x, , z] = frame.toWorld(c.x, c.y, 1.5);
      const pts = path.centerline;
      const len = pts.reduce((acc, p, i) => (i ? acc + Math.hypot(p.x - pts[i - 1].x, p.y - pts[i - 1].y) : acc), 0);
      return { kind: 'box', pos: [x, 1.5, z] as [number, number, number], size: [Math.max(8, len * 0.6), 3.2, (path.width_m ?? 3) * 2.4] as [number, number, number] };
    }
    return null;
  }, [bottleneck, spatial, frame]);

  const color = riskColor(bottleneck.current_risk, palette);
  const [pulse, setPulse] = useState(0);
  useFrame(({ clock }) => setPulse(0.5 + 0.2 * Math.sin(clock.getElapsedTime() * 3)));

  if (!region) return null;
  return (
    <group>
      <mesh position={region.pos} onClick={(e) => { e.stopPropagation(); onClick(); }}>
        <boxGeometry args={region.size} />
        <meshStandardMaterial
          color={color}
          transparent
          opacity={0.22 + pulse * 0.15}
          emissive={color}
          emissiveIntensity={0.35}
          depthWrite={false}
        />
      </mesh>
      {/* pulsing wireframe shell */}
      <mesh position={region.pos} scale={1 + pulse * 0.15}>
        <boxGeometry args={region.size} />
        <meshBasicMaterial color={color} wireframe transparent opacity={0.5} depthWrite={false} />
      </mesh>
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Congestion floor glow for live/selected bottleneck
// --------------------------------------------------------------------------- //
function CongestionGlow({ bottleneck, frame, palette }: { bottleneck: Bottleneck; frame: Frame; palette: TwinPalette }) {
  const [x, , z] = frame.toWorld(bottleneck.location === 'PITCH' ? 500 : 500, 300);
  const color = riskColor(bottleneck.current_risk, palette);
  return (
    <mesh position={[x, 0.35, z]} rotation={[-Math.PI / 2, 0, 0]}>
      <circleGeometry args={[22, 40]} />
      <meshBasicMaterial color={color} transparent opacity={0.28} depthWrite={false} />
    </mesh>
  );
}

// --------------------------------------------------------------------------- //
//  Camera rig — presets OVERVIEW / FOCUS / FOLLOW / GROUND
// --------------------------------------------------------------------------- //
function CameraRig({ preset, focus, spatial, venue }: { preset: CameraPreset; focus: TwinPick | null; spatial: VenueSpatialModel; venue: VenueModel }) {
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as unknown as {
    target: THREE.Vector3;
    update: () => void;
  } | null;
  const frame = useMemo(() => makeFrame(venue.width, venue.height), [venue]);
  const targetRef = useRef<THREE.Vector3 | null>(null);
  const presetPos = useRef<THREE.Vector3>(new THREE.Vector3());

  const desired = useMemo(() => {
    const target = new THREE.Vector3(0, 4, 0);
    const focusPoint = (() => {
      if (!focus) return null;
      if (focus.kind === 'opening') {
        const o = spatial.openings.find((x) => x.id === focus.id);
        if (o) { const [x, , z] = frame.toWorld(o.position.x, o.position.y); return new THREE.Vector3(x, 0, z); }
      }
      if (focus.kind === 'path') {
        const p = spatial.paths.find((x) => x.id === focus.id);
        if (p?.centerline.length) { const c = p.centerline[Math.floor(p.centerline.length / 2)]; const [x, , z] = frame.toWorld(c.x, c.y); return new THREE.Vector3(x, 0, z); }
      }
      if (focus.kind === 'structure') {
        const s = spatial.structures.find((x) => x.id === focus.id);
        if (s) { const c = s.polygon.points.reduce((a, p) => ({ x: a.x + p.x / s.polygon.points.length, y: a.y + p.y / s.polygon.points.length }), { x: 0, y: 0 }); const [x, , z] = frame.toWorld(c.x, c.y); return new THREE.Vector3(x, 0, z); }
      }
      return null;
    })();

    let pos: THREE.Vector3;
    switch (preset) {
      case 'overview':
        pos = new THREE.Vector3(venue.width * 0.9, venue.height * 1.15, venue.height * 1.5);
        break;
      case 'focus':
        if (focusPoint) {
          target.copy(focusPoint);
          pos = focusPoint.clone().add(new THREE.Vector3(40, 55, 60));
        } else pos = new THREE.Vector3(venue.width * 0.7, 90, venue.height * 1.1);
        break;
      case 'ground': {
        const fp = focusPoint ?? new THREE.Vector3(0, 0, 0);
        target.copy(fp);
        pos = fp.clone().add(new THREE.Vector3(8, 2.2, 10));
        break;
      }
      case 'follow':
      default:
        pos = new THREE.Vector3(venue.width * 0.55, venue.height * 0.75, venue.height * 1.0);
        break;
    }
    return { pos, target: target.clone() };
  }, [preset, focus, spatial, venue, frame]);

  useEffect(() => {
    targetRef.current = desired.target.clone();
    presetPos.current.copy(desired.pos);
    if (controls) {
      controls.target.copy(desired.target);
      controls.update();
    }
  }, [desired, controls]);

  useFrame(() => {
    if (camera.position.distanceTo(presetPos.current) > 1.5) {
      camera.position.lerp(presetPos.current, 0.08);
    } else {
      camera.position.copy(presetPos.current);
    }
    if (controls) {
      controls.target.lerp(targetRef.current ?? desired.target, 0.12);
      controls.update();
    }
  });

  return null;
}

// --------------------------------------------------------------------------- //
//  Generated GLB venue shell (AI / procedural 3D twin).
//  - mode 'world': GLB is already in the twin world frame (procedural /
//    simulated geometry built by the worker), so it is rendered untransformed.
//  - mode 'auto': raw AI mesh with arbitrary scale/orientation. It is fitted so
//    its horizontal footprint spans `fitSize` world meters, centred on the venue
//    origin and resting on the ground plane. Flat relief meshes (thin in one
//    axis, e.g. Hunyuan reconstructions of blueprints) are laid flat on the
//    ground; upright objects stay upright.
// --------------------------------------------------------------------------- //
function GlbShell({ url, mode, fitSize }: { url: string; mode: 'world' | 'auto'; fitSize: number }) {
  const gltf = useGLTF(url);
  const scene = gltf.scene;

  const fitted = useMemo(() => {
    if (mode !== 'auto') return null;
    const box = new THREE.Box3().setFromObject(scene);
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    if (!isFinite(maxDim) || maxDim <= 0 || !isFinite(fitSize) || fitSize <= 0) return null;

    const rotation = new THREE.Euler();
    const minDim = Math.min(size.x, size.y, size.z);
    if (minDim / maxDim < 0.3) {
      if (size.z <= minDim + 1e-9) rotation.set(-Math.PI / 2, 0, 0);
      else if (size.x <= minDim + 1e-9) rotation.set(0, 0, Math.PI / 2);
    }

    const rotMat = new THREE.Matrix4().makeRotationFromEuler(rotation);
    const rotBox = box.clone().applyMatrix4(rotMat);
    const rSize = rotBox.getSize(new THREE.Vector3());
    const footExtent = Math.max(rSize.x, rSize.z);
    const scale = footExtent > 0 ? fitSize / footExtent : 1;
    const center = rotBox.getCenter(new THREE.Vector3());
    return {
      rotation: [rotation.x, rotation.y, rotation.z] as [number, number, number],
      scale,
      x: -center.x * scale,
      y: -rotBox.min.y * scale,
      z: -center.z * scale,
    };
  }, [scene, mode, fitSize]);

  if (!fitted) return <primitive object={scene} castShadow receiveShadow />;
  return (
    <group rotation={fitted.rotation} scale={fitted.scale} position={[fitted.x, fitted.y, fitted.z]}>
      <primitive object={scene} castShadow receiveShadow />
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Scene assembly
// --------------------------------------------------------------------------- //
function TwinScene({
  venue,
  spatial,
  palette,
  sim,
  compareSim,
  compareSide,
  bottlenecks,
  selected,
  onPick,
  mode,
  cameraPreset,
  onBottleneckSelect,
  glbUrl,
  glbMode = 'world',
}: TwinProps & { palette: TwinPalette }) {
  const frame = useMemo(() => makeFrame(venue.width, venue.height), [venue]);
  const glbFitSize = useMemo(
    () => Math.min(venue.width, venue.height) * 0.6,
    [venue],
  );
  const maxAgents = Math.max(
    (sim?.agents?.length ?? 0) * 2,
    (compareSim?.agents?.length ?? 0) * 2,
    1,
  );

  const activeSim = compareSim && compareSide === 'whatif' ? compareSim : sim;
  const agents = activeSim?.agents ?? [];

  const byLevel = useMemo(() => {
    const map = new Map<string, { structures: StructureModel[]; paths: PathGeometryModel[]; openings: OpeningModel[] }>();
    for (const s of spatial.structures) (map.get(s.level_id) ?? map.set(s.level_id, { structures: [], paths: [], openings: [] }).get(s.level_id)!).structures.push(s);
    for (const p of spatial.paths) (map.get(p.level_id) ?? map.set(p.level_id, { structures: [], paths: [], openings: [] }).get(p.level_id)!).paths.push(p);
    for (const o of spatial.openings) (map.get(o.level_id) ?? map.set(o.level_id, { structures: [], paths: [], openings: [] }).get(o.level_id)!).openings.push(o);
    return map;
  }, [spatial]);

  const bottleneckByLoc = useMemo(() => {
    const m = new Map<string, Bottleneck>();
    bottlenecks.forEach((b) => m.set(b.location, b));
    return m;
  }, [bottlenecks]);

  return (
    <group>
      <gridHelper args={[Math.max(venue.width, venue.height) * 2, 20, palette.line, palette.line]} position={[0, 0.01, 0]} />
      {glbUrl && <GlbShell url={glbUrl} mode={glbMode} fitSize={glbFitSize} />}
      {spatial.levels.map((level: LevelModel) => {
        const items = byLevel.get(level.id) ?? { structures: [], paths: [], openings: [] };
        return (
          <group key={level.id} position={[0, level.elevation_m ?? 0, 0]}>
            {(!glbUrl || glbMode === 'auto') && items.structures.map((s) => (
              <StructureMesh
                key={s.id}
                structure={s}
                frame={frame}
                palette={palette}
                selected={selected?.kind === 'structure' && selected.id === s.id}
                onPick={onPick}
                live={mode === 'live' && compareSide !== 'whatif'}
              />
            ))}
            {items.paths.map((p) => (
              <PathBand
                key={p.id}
                path={p}
                frame={frame}
                palette={palette}
                selected={selected?.kind === 'path' && selected.id === p.id}
                onPick={onPick}
                congestion={bottleneckByLoc.get(p.id)?.current_risk ?? null}
              />
            ))}
            {items.openings.map((o) => (
              <OpeningMarker
                key={o.id}
                opening={o}
                frame={frame}
                palette={palette}
                selected={selected?.kind === 'opening' && selected.id === o.id}
                onPick={onPick}
                congestion={bottleneckByLoc.get(o.id)?.current_risk ?? bottleneckByLoc.get(`E_${o.id}`)?.current_risk ?? null}
              />
            ))}
          </group>
        );
      })}

      {/* crowd inside the twin */}
      <Crowd agents={agents} frame={frame} palette={palette} maxAgents={Math.max(maxAgents, agents.length)} />

      {/* live congestion glows */}
      {mode !== 'predict' && bottlenecks.slice(0, 3).map((b) => <CongestionGlow key={`glow-${b.location}`} bottleneck={b} frame={frame} palette={palette} />)}

      {/* spatial prediction volumes */}
      {mode === 'predict' && bottlenecks.slice(0, 4).map((b) => (
        <PredictionVolume
          key={`pred-${b.location}`}
          bottleneck={b}
          spatial={spatial}
          frame={frame}
          palette={palette}
          onClick={() => onBottleneckSelect(b)}
        />
      ))}

      <CameraRig preset={cameraPreset} focus={selected} spatial={spatial} venue={venue} />
    </group>
  );
}

// --------------------------------------------------------------------------- //
//  Public renderer
// --------------------------------------------------------------------------- //
export default function DigitalTwinRenderer(props: TwinProps) {
  const { venue, spatial, onPick } = props;
  const palette = TWIN_PALETTE;

  if (!spatial) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-od-canvas">
        <div className="shimmer-line h-3 w-44" />
      </div>
    );
  }

  return (
    <div className="relative h-full w-full bg-od-canvas">
      <Canvas
        shadows
        dpr={[1, 2]}
        gl={{ preserveDrawingBuffer: true, antialias: true }}
        camera={{ position: [venue.width * 0.9, venue.height * 1.15, venue.height * 1.5], fov: 38, near: 0.5, far: venue.width * 20 }}
        onPointerMissed={() => onPick(null)}
      >
        <color attach="background" args={[palette.canvas]} />
        <fog attach="fog" args={[palette.canvas, venue.width * 1.2, venue.width * 3.4]} />
        <ambientLight intensity={0.75} />
        <directionalLight position={[venue.width * 0.6, venue.height, venue.height * 0.5]} intensity={1.5} castShadow />
        <directionalLight position={[-venue.width * 0.4, venue.height * 0.4, -venue.height * 0.5]} intensity={0.45} />
        <Suspense fallback={null}>
          <TwinScene {...props} palette={palette} />
        </Suspense>
        <OrbitControls
          makeDefault
          enableDamping
          dampingFactor={0.08}
          minDistance={venue.width * 0.12}
          maxDistance={venue.width * 4}
          maxPolarAngle={Math.PI / 2.02}
        />
      </Canvas>
      {/* override cursor cleanup */}
      <style>{`canvas { outline: none; }`}</style>
    </div>
  );
}
