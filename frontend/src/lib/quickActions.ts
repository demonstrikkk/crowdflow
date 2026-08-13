import type { Bottleneck, VenueModel, SimulationState, Intervention } from './types';

/**
 * A one-click intervention button surfaced in the investigation panel.
 *
 * Defined here (not in lib/types.ts) per Req 22.
 */
export interface QuickAction {
  /** Short action label displayed on the button */
  label: string;
  /** Longer description rendered below the label */
  description: string;
  /**
   * Pre-built intervention payload — the `id` field is intentionally
   * omitted here and must be supplied (e.g. via `crypto.randomUUID()`)
   * by the caller before passing to `applyIntervention`.
   */
  intervention: Omit<Intervention, 'id'>;
  /** Visual variant for the button */
  variant: 'warn' | 'ok' | 'ghost';
}

/**
 * Compute quick-action buttons for a given bottleneck.
 *
 * Algorithm (Req 10.1 / Req 10.2 / design §2.2):
 *  1. Find up to two alternate open edges that originate at the bottleneck
 *     source node (excluding the bottleneck edge itself) → REDIRECT actions
 *     with `variant: 'ok'`.
 *  2. Always append a CLOSE_CORRIDOR fallback for the bottleneck edge itself
 *     with `variant: 'warn'`.
 *
 * The function always returns at least one action (the fallback) — Req 10.1.
 *
 * @param bottleneck  The active bottleneck being investigated
 * @param venue       The venue model (provides edge topology)
 * @param sim         Current simulation state (not used in routing logic but
 *                    available for callers that may need it; kept in signature
 *                    for future extension)
 * @returns           Non-empty QuickAction array
 */
export function quickActionsFor(
  bottleneck: Bottleneck,
  venue: VenueModel,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  _sim: SimulationState,
): QuickAction[] {
  const actions: QuickAction[] = [];

  // Extract source node from the bottleneck location (format: "SRC→DST")
  const [src] = bottleneck.location.split('→');

  // Find up to two open alternate edges from the same source node (Req 10.2)
  const alternateEdges = venue.edges
    .filter(
      (e) =>
        e.source === src &&
        e.id !== bottleneck.location &&
        // Also guard against the edge string key form used in some contexts
        `${e.source}→${e.destination}` !== bottleneck.location &&
        e.is_open,
    )
    .slice(0, 2);

  for (const alt of alternateEdges) {
    actions.push({
      label: `Open alternate: ${alt.destination}`,
      description: `Redirect flow via ${alt.destination.replace(/_/g, ' ')}`,
      intervention: {
        type: 'REDIRECT',
        description: `Redirect from ${src} via ${alt.destination}`,
        parameters: { from: src, to: alt.destination, pct: 30 },
      },
      variant: 'ok',
    });
  }

  // Always append the CLOSE_CORRIDOR fallback (Req 10.1)
  actions.push({
    label: 'Close this corridor',
    description: 'Force reroute all agents away from this segment',
    intervention: {
      type: 'CLOSE_CORRIDOR',
      description: `Close ${bottleneck.location}`,
      parameters: { edge: bottleneck.location },
    },
    variant: 'warn',
  });

  return actions;
}
