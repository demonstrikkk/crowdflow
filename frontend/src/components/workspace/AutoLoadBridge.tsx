import { useEffect, useRef } from 'react';
import { useSimulation } from '../../store/SimulationContext';

/**
 * AutoLoadBridge — renders nothing, fires once to auto-select the demo venue
 * and default scenario when the app first loads with venues available.
 *
 * Conditions for activation:
 *   - venues have loaded (length > 0)
 *   - no venue is currently selected (venue === null)
 *   - has not already fired (didAutoLoad ref guard)
 *
 * Venue preference: 'unity_arena' → fallback to venues[0]
 * Scenario preference: sc.special.default === true && sc.venue_id === demo.id
 *                      → fallback to first scenario for that venue
 *
 * Requirements: Req 14, Req 20
 */
export function AutoLoadBridge() {
  const s = useSimulation();
  const didAutoLoad = useRef(false);

  useEffect(() => {
    // Idempotency guard — never run more than once
    if (didAutoLoad.current) return;

    // No-op when venues haven't loaded yet or a venue is already selected
    if (s.venues.length === 0 || s.venue !== null) return;

    // Mark as done BEFORE any async work to prevent double-fire
    didAutoLoad.current = true;

    // Prefer the seeded demo venue; fall back to first available venue
    const demo = s.venues.find((v) => v.id === 'unity_arena') ?? s.venues[0];

    s.selectVenue(demo.id);

    // Auto-select the default scenario for this venue
    const defaultScenario =
      s.scenarios.find(
        (sc) => sc.special?.['default'] === true && sc.venue_id === demo.id,
      ) ??
      s.scenarios.find((sc) => sc.venue_id === demo.id) ??
      null;

    if (defaultScenario) {
      void s.selectScenario(defaultScenario.id);
    }
  }, [s.venues, s.venue, s.scenarios]); // eslint-disable-line react-hooks/exhaustive-deps

  // First-run golden demo: once a venue + scenario are ready and no simulation
  // is running, auto-start the event so the living world is alive immediately.
  const autoStarted = useRef(false);
  useEffect(() => {
    if (autoStarted.current) return;
    if (!s.venue || !s.scenario || s.sim || s.busy) return;
    autoStarted.current = true;
    void s.runSimulation();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.venue, s.scenario, s.sim, s.busy]);

  // Begin live playback the moment the simulation WebSocket is live.
  const autoPlayed = useRef(false);
  useEffect(() => {
    if (autoPlayed.current) return;
    if (!s.wsConnected || !s.sim || !s.simId) return;
    autoPlayed.current = true;
    void s.play();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.wsConnected, s.sim, s.simId]);

  return null;
}

export default AutoLoadBridge;
