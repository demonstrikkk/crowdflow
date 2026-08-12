import type { NodeModel, VenueModel } from './types';

export type Mode = 'simulate' | 'investigate' | 'intervene' | 'compare';

export type WorkspaceView = Mode | 'scenarios' | 'venues' | 'settings' | 'twin3d' | 'blueprint';

export type Selection =
  | { kind: 'edge'; id: string }
  | { kind: 'node'; id: string };

export function edgeKey(u: string, v: string): string {
  return `${u}→${v}`;
}

export function nodeById(venue: VenueModel | null, id: string): NodeModel | null {
  return venue?.nodes.find((n) => n.id === id) ?? null;
}

export function positionsOf(venue: VenueModel | null, nodes?: Record<string, { x: number; y: number }>) {
  const out = new Map<string, { x: number; y: number }>();
  if (nodes) {
    for (const [id, pos] of Object.entries(nodes)) out.set(id, pos);
  }
  for (const n of venue?.nodes ?? []) {
    if (!out.has(n.id)) out.set(n.id, n.position);
  }
  return out;
}