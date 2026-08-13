import { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronLeft } from 'lucide-react';
import { useSimulation } from '../../store/SimulationContext';
import type { CompareViewMode } from '../../store/SimulationContext';
import type { Mode, Selection, WorkspaceView } from '../../lib/selection';
import { edgeKey as edgeKeyOf } from '../../lib/selection';
import type { ExternalEnvironment, Intervention } from '../../lib/types';
import { api } from '../../lib/api';
import InstrumentCanvas, { type CanvasScope, type DraftState, type SpatialAction } from './InstrumentCanvas';
import DeltaInstrumentCanvas from './DeltaInstrumentCanvas';
import CommandBarBanner from './CommandBarBanner';
import TopBar from './TopBar';
import ContextPanel from './ContextPanel';
import Timeline from './Timeline';
import StatusBar from './StatusBar';
import EmptyState from './EmptyState';
import GuidedCard from './GuidedCard';
import { ViewRail } from './ViewRail';
import { HumanBehaviourOverlay, type BehaviourField } from './HumanBehaviourOverlay';

const SPEEDS = [10, 30, 80, 240];

const makeIntervention = (partial: Omit<Intervention, 'id'>): Intervention => ({
  id: typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
  ...partial,
});

export default function Instrument({ mode, onMode }: { mode: Mode; onMode: (m: WorkspaceView) => void }) {
  const s = useSimulation();
  const [selected, setSelected] = useState<Selection | null>(null);
  const [drafts, setDrafts] = useState<DraftState | null>(null);
  const [behaviourField, setBehaviourField] = useState<BehaviourField>('stress');
  const [env, setEnv] = useState<ExternalEnvironment | null>(null);
  const [scope, setScope] = useState<CanvasScope>('venue');
  const [panelOpen, setPanelOpen] = useState<boolean>(() => {
    try {
      return localStorage.getItem('cf-panel-open') !== 'false';
    } catch {
      return true;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem('cf-panel-open', String(panelOpen));
    } catch {
      /* storage unavailable */
    }
  }, [panelOpen]);
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

  // spatial actions issued from the venue canvas itself
  const onSpatialAction = useCallback(
    (action: SpatialAction) => {
      const sel = action.selection;
      const node = sel.kind === 'node' ? s.venue?.nodes.find((n) => n.id === sel.id) ?? null : null;
      const incidentEdges =
        sel.kind === 'node'
          ? (s.venue?.edges.filter((e) => e.source === sel.id || e.destination === sel.id).map((e) => edgeKeyOf(e.source, e.destination)) ?? [])
          : [];

      switch (action.type) {
        case 'close': {
          const targets = sel.kind === 'edge' ? [sel.id] : incidentEdges;
          setDrafts((d) => {
            const cur = d?.closedEdgeIds ?? [];
            const next = [...new Set([...cur, ...targets])];
            return { closedEdgeIds: next, redirect: d?.redirect ?? null };
          });
          break;
        }
        case 'open': {
          const targets = sel.kind === 'edge' ? [sel.id] : incidentEdges;
          setDrafts((d) => ({
            closedEdgeIds: (d?.closedEdgeIds ?? []).filter((k) => !targets.includes(k)),
            redirect: d?.redirect ?? null,
          }));
          break;
        }
        case 'redirect': {
          if (node && node.type === 'ENTRY') {
            const target = s.venue?.nodes.find((n) => n.type === 'EXIT');
            if (target) setDrafts((d) => ({ closedEdgeIds: d?.closedEdgeIds ?? [], redirect: { from: node.id, to: target.id, pct: 20 } }));
          }
          break;
        }
        case 'incident': {
          setSelected(sel);
          break;
        }
      }
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

  // auto-offer: the system proposes testing an alternative when a bottleneck forms
  const testAlternative = useCallback(() => {
    const loc = topBottleneck?.location;
    if (!loc) return;
    const intervention = makeIntervention({
      type: 'CLOSE_CORRIDOR',
      description: `Close ${loc} (alternative)`,
      parameters: { edge: loc },
    });
    void s.runCounterfactual(intervention).then(() => onMode('compare'));
  }, [topBottleneck, s, onMode]);

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
      onSpatialAction={interactive && mode === 'intervene' ? onSpatialAction : undefined}
      simRef={s.simRef}
      viewMode={s.viewMode}
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

      <CommandBarBanner />

      <div className="flex min-h-0 flex-1">
        <ViewRail viewMode={s.viewMode} onChange={s.setViewMode} />
        <div className="relative min-w-0 flex-1">
          {s.viewMode === 'behaviour' && (
            <HumanBehaviourOverlay field={behaviourField} onFieldChange={setBehaviourField} />
          )}

          {mode === 'compare' && s.cfSim !== null ? (
            <div className="absolute inset-0 flex flex-col">
              {/* Toggle strip */}
              <div className="flex shrink-0 items-center gap-1.5 border-b border-od-line bg-od-panel px-3 py-1.5">
                {(['baseline', 'counterfactual', 'delta'] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => s.setCompareViewMode(m)}
                    className={`chip ${s.compareViewMode === m ? 'is-active' : ''}`}
                  >
                    {m.toUpperCase()}
                  </button>
                ))}
              </div>
              {/* Split canvas area */}
              <div className="flex min-h-0 flex-1 divide-x divide-od-line">
                {/* Left pane: always baseline */}
                <div className="relative min-w-0 flex-1">
                  <InstrumentCanvas sim={s.displayedSim} venue={s.venue} mode="compare" selected={null} interactive={false} showAgents showLabels environment={env} scope={scope} />
                </div>
                {/* Right pane: counterfactual OR delta */}
                <div className="relative min-w-0 flex-1">
                  {s.compareViewMode === 'delta' && s.cfSim && s.venue ? (
                    <DeltaInstrumentCanvas baseSim={s.displayedSim!} cfSim={s.cfSim} venue={s.venue} />
                  ) : (
                    <InstrumentCanvas sim={s.cfSim} venue={s.venue} mode="compare" selected={null} interactive={false} showAgents showLabels environment={env} scope={scope} />
                  )}
                </div>
              </div>
            </div>
          ) : mode === 'compare' ? (
            <div className="absolute inset-0">{singleCanvas(false, false)}</div>
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

          {mode === 'simulate' && topBottleneck && !s.cfSimId && (
            <div className="absolute top-3 left-3 z-10 flex items-center gap-3 border border-od-warn bg-od-panel px-3 py-2 shadow-[0_16px_48px_-24px_rgba(0,0,0,0.7)]">
              <span className="status-dot is-warn" />
              <div>
                <div className="sec-label">Bottleneck · {topBottleneck.location}</div>
                <div className="num mt-0.5 text-[12px] font-bold text-od-ink">{topBottleneck.explanation}</div>
              </div>
              <button className="btn btn-solid" onClick={testAlternative}>
                TEST ALTERNATIVE
              </button>
            </div>
          )}
          {mode === 'intervene' && !s.cfSimId && (
            <button
              className="absolute top-3 right-3 z-10 btn btn-solid"
              onClick={runAsCounterfactual}
              disabled={!drafts?.redirect && (drafts?.closedEdgeIds.length ?? 0) === 0}
            >
              RUN AS COUNTERFACTUAL
            </button>
          )}

          {s.venue !== null && s.sim === null && (
            <div className="absolute inset-0 z-20" style={{ backdropFilter: 'blur(2px)', background: 'rgba(var(--od-canvas-rgb, 10 12 14), 0.55)' }}>
              <div className="flex h-full items-center justify-center">
                <div className="text-center space-y-4 px-8">
                  <div className="sec-label">{s.venue.name}</div>
                  {s.scenario && <div className="text-od-muted text-[11px]">{s.scenario.name} · {s.scenario.crowd_size.toLocaleString()} crowd</div>}
                  <button
                    className="h-14 px-10 text-base font-bold btn btn-solid"
                    onClick={() => void s.runSimulation()}
                  >
                    ▶ SIMULATE
                  </button>
                  {!s.scenario && (
                    <div>
                      <button className="btn btn-ghost" onClick={() => onMode('scenarios')}>Choose scenario</button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
          {!s.venue && (
            <div className="absolute inset-0 z-20">
              <EmptyState
                venueName={null}
                onLoad={() => void s.runSimulation()}
                onBuild={() => onMode('scenarios')}
                onImport={() => onMode('venues')}
                hasScenario={!!s.scenario}
              />
            </div>
          )}
        </div>

        {panelOpen ? (
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
            onClosePanel={() => setPanelOpen(false)}
            viewMode={s.viewMode}
          />
        ) : (
          <button
            onClick={() => setPanelOpen(true)}
            className="hidden lg:flex w-8 shrink-0 flex-col items-center justify-center gap-2 border-l border-od-line bg-od-panel text-od-muted hover:text-od-ink cursor-pointer"
            aria-label="Show context panel"
            title="Show context panel"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            <span className="[writing-mode:vertical-rl] text-[9px] uppercase tracking-[0.22em]">Context</span>
          </button>
        )}
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