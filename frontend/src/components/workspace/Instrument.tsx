import { useCallback, useEffect, useRef, useState } from 'react';
import { useSimulation } from '../../store/SimulationContext';
import type { Mode, Selection, WorkspaceView } from '../../lib/selection';
import type { ExternalEnvironment, Intervention } from '../../lib/types';
import { api } from '../../lib/api';
import InstrumentCanvas, { type CanvasScope, type DraftState } from './InstrumentCanvas';
import TopBar from './TopBar';
import ContextPanel from './ContextPanel';
import Timeline from './Timeline';
import StatusBar from './StatusBar';
import EmptyState from './EmptyState';
import GuidedCard from './GuidedCard';

const SPEEDS = [10, 30, 80, 240];

const makeIntervention = (partial: Omit<Intervention, 'id'>): Intervention => ({
  id: typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
  ...partial,
});

export default function Instrument({ mode, onMode }: { mode: Mode; onMode: (m: WorkspaceView) => void }) {
  const s = useSimulation();
  const [selected, setSelected] = useState<Selection | null>(null);
  const [drafts, setDrafts] = useState<DraftState | null>(null);
  const [env, setEnv] = useState<ExternalEnvironment | null>(null);
  const [scope, setScope] = useState<CanvasScope>('venue');
  const draftRef = useRef(drafts);
  draftRef.current = drafts;

  // load the surrounding road network whenever the venue changes
  useEffect(() => {
    let cancelled = false;
    if (!s.venue) {
      setEnv(null);
      setScope('venue');
      return;
    }
    setEnv(null);
    api
      .environment(s.venue.id)
      .then((e) => {
        if (!cancelled) setEnv(e);
      })
      .catch(() => {
        if (!cancelled) setEnv(null);
      });
    return () => {
      cancelled = true;
    };
  }, [s.venue]);

  const refreshEnvironment = useCallback(() => {
    if (!s.venue) return;
    api
      .refreshEnvironment(s.venue.id)
      .then(setEnv)
      .catch(() => {
        /* keep current environment */
      });
  }, [s.venue]);

  const topBottleneck = s.displayedSim?.bottlenecks[0] ?? null;

  const onToggleClose = useCallback((edgeKey: string) => {
    setDrafts((d) => {
      const cur = d?.closedEdgeIds ?? [];
      const next = cur.includes(edgeKey) ? cur.filter((k) => k !== edgeKey) : [...cur, edgeKey];
      return { closedEdgeIds: next, redirect: d?.redirect ?? null };
    });
  }, []);

  const onImplementClose = useCallback(
    (edgeKey: string) => {
      s.applyIntervention(
        makeIntervention({ type: 'CLOSE_CORRIDOR', description: `Close ${edgeKey}`, parameters: { edge: edgeKey } }),
      );
      setDrafts((d) => ({ closedEdgeIds: (d?.closedEdgeIds ?? []).filter((k) => k !== edgeKey), redirect: d?.redirect ?? null }));
    },
    [s],
  );

  const onSetRedirect = useCallback((r: DraftState['redirect']) => {
    setDrafts((d) => ({ closedEdgeIds: d?.closedEdgeIds ?? [], redirect: r }));
  }, []);

  const onImplementRedirect = useCallback(
    (r: NonNullable<DraftState['redirect']>) => {
      s.applyIntervention(
        makeIntervention({
          type: 'REDIRECT',
          description: `Redirect ${r.from} → ${r.to} (${r.pct}%)`,
          parameters: { from: r.from, to: r.to, pct: r.pct },
        }),
      );
      setDrafts((d) => ({ closedEdgeIds: d?.closedEdgeIds ?? [], redirect: null }));
    },
    [s],
  );

  const onEmergency = useCallback(
    (active: boolean) => {
      s.setEmergency(active);
    },
    [s],
  );

  const guidedCta = useCallback(() => {
    const loc = topBottleneck?.location;
    onMode('intervene');
    if (loc) {
      setSelected({ kind: 'edge', id: loc });
      setDrafts((d) => ({ closedEdgeIds: [...(d?.closedEdgeIds ?? []), loc], redirect: d?.redirect ?? null }));
    }
    s.dismissGuided();
  }, [topBottleneck, onMode, s]);

  const runAsCounterfactual = useCallback(() => {
    const d = draftRef.current;
    let intervention: Parameters<typeof s.runCounterfactual>[0] | null = null;
    if (d?.redirect) {
      intervention = makeIntervention({
        type: 'REDIRECT',
        description: `Redirect ${d.redirect.from} → ${d.redirect.to} (${d.redirect.pct}%)`,
        parameters: { from: d.redirect.from, to: d.redirect.to, pct: d.redirect.pct },
      });
    } else if (d?.closedEdgeIds.length) {
      intervention = makeIntervention(
        d.closedEdgeIds.map((edge) => ({
          type: 'CLOSE_CORRIDOR' as const,
          description: `Close ${edge}`,
          parameters: { edge },
        }))[0]!,
      );
    }
    if (intervention) {
      void s.runCounterfactual(intervention).then(() => onMode('compare'));
    }
  }, [s, onMode]);

  const singleCanvas = (interactive: boolean, showDrafts: boolean) => (
    <InstrumentCanvas
      sim={s.displayedSim}
      venue={s.venue}
      mode={mode}
      selected={selected}
      onSelect={setSelected}
      interactive={interactive}
      showAgents
      showLabels
      guided={s.guided}
      drafts={showDrafts ? drafts : null}
      environment={env}
      scope={scope}
      onScope={interactive ? setScope : undefined}
      onRefreshEnvironment={interactive ? refreshEnvironment : undefined}
    />
  );

  return (
    <div className="flex h-full w-full flex-col bg-od-canvas">
      <TopBar
        mode={mode}
        venue={s.venue}
        scenario={s.scenario}
        scenarios={s.scenarios}
        onScenario={(id) => void s.selectScenario(id)}
        sim={s.sim}
        wsConnected={s.wsConnected}
        onPlay={() => void s.play()}
        onPause={() => void s.pause()}
      />

      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          {mode === 'compare' ? (
            <div className="absolute inset-0 grid grid-cols-2 divide-x divide-od-line">
              <div className="relative min-w-0">
                <div className="absolute top-2 left-3 z-10 text-[9px] uppercase tracking-[0.22em] text-od-muted bg-od-panel px-1.5 py-0.5">
                  Baseline
                </div>
                <div className="absolute inset-0">
                  <InstrumentCanvas sim={s.displayedSim} venue={s.venue} mode="compare" selected={null} interactive={false} showAgents showLabels environment={env} scope={scope} />
                </div>
              </div>
              <div className="relative min-w-0">
                <div className="absolute top-2 left-3 z-10 text-[9px] uppercase tracking-[0.22em] text-od-warn bg-od-panel px-1.5 py-0.5">
                  Counterfactual
                </div>
                <div className="absolute inset-0">
                  <InstrumentCanvas sim={s.cfSim} venue={s.venue} mode="compare" selected={null} interactive={false} showAgents showLabels environment={env} scope={scope} />
                </div>
              </div>
            </div>
          ) : (
            <div className="absolute inset-0">{singleCanvas(true, mode === 'intervene')}</div>
          )}

          {mode === 'simulate' && s.guided === 'bottleneck' && topBottleneck && (
            <GuidedCard
              location={topBottleneck.location}
              onAct={guidedCta}
              onDismiss={s.dismissGuided}
            />
          )}

          {mode === 'intervene' && !s.cfSimId && (
            <button
              className="absolute top-3 right-3 z-10 btn btn-solid"
              onClick={runAsCounterfactual}
              disabled={!drafts?.redirect && (drafts?.closedEdgeIds.length ?? 0) === 0}
            >
              RUN AS COUNTERFACTUAL ▶
            </button>
          )}

          {!s.sim && !s.cfSimId && (
            <div className="absolute inset-0 z-20">
              <EmptyState
                onLoad={() => void s.runSimulation()}
                onBuild={() => onMode('scenarios')}
                onImport={() => onMode('venues')}
                hasScenario={!!s.scenario}
              />
            </div>
          )}
        </div>

        <ContextPanel
          mode={mode}
          sim={s.displayedSim}
          venue={s.venue}
          selected={selected}
          onSelect={setSelected}
          guidedCta={mode === 'simulate' && s.guided === 'bottleneck' ? guidedCta : null}
          drafts={drafts}
          onToggleClose={onToggleClose}
          onImplementClose={onImplementClose}
          onSetRedirect={onSetRedirect}
          onImplementRedirect={onImplementRedirect}
          onEmergency={onEmergency}
          onIntervention={(i) => void s.applyIntervention(i)}
          cfSim={s.cfSim}
          cfError={s.cfError}
          onDiscardCf={s.discardCounterfactual}
          onApplyCf={() => void s.applyCounterfactual()}
          runCounterfactual={s.runCounterfactual}
        />
      </div>

      <Timeline
        buffer={s.buffer}
        frameIndex={s.frameIndex}
        seeking={s.seeking}
        tMin={s.sim?.t_min ?? 0}
        status={s.sim?.status ?? 'IDLE'}
        phases={s.scenario?.event_phases ?? []}
        speed={s.sim?.speed ?? 10}
        speeds={SPEEDS}
        onSeek={s.seekFrame}
        onJump={(min) => void s.jumpToMinute(min)}
        onPlay={() => void s.play()}
        onPause={() => void s.pause()}
        onRewind={() => void s.jumpToMinute(0)}
        onSpeed={(sp) => void s.setSpeed(sp)}
        simId={s.simId}
      />

      <StatusBar sim={s.sim} wsConnected={s.wsConnected} />
    </div>
  );
}