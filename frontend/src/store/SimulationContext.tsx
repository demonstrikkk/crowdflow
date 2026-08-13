import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import * as React from 'react';
import { api, wsUrl } from '../lib/api';
import type {
  AiExplainResponse,
  AiProviderStatus,
  AiSuggestion,
  Intervention,
  OptimizationResult,
  ScenarioDelta,
  ScenarioModel,
  SimulationState,
  VenueModel,
  ViewMode,
} from '../lib/types';


export type GuidedStep = 'idle' | 'running' | 'bottleneck' | 'done';
export type ThemeMode = 'light' | 'dark';
export type CompareViewMode = 'baseline' | 'counterfactual' | 'delta';

export interface PlaybackFrame extends SimFrame {
  t: number;
}

type SimFrame = SimulationState;

interface SimulationContextValue {
  backendOnline: boolean | null;
  venues: VenueModel[];
  scenarios: ScenarioModel[];
  venue: VenueModel | null;
  scenario: ScenarioModel | null;
  sim: SimulationState | null;
  simId: string | null;
  wsConnected: boolean;
  busy: boolean;
  error: string | null;
  optimization: OptimizationResult | null;
  optimizing: boolean;
  theme: ThemeMode;
  toggleTheme: () => void;
  guided: GuidedStep;
  dismissGuided: () => void;
  buffer: PlaybackFrame[];
  frameIndex: number;
  seeking: boolean;
  seekFrame: (i: number) => void;
  resumeLive: () => void;
  displayedSim: SimulationState | null;
  bufferStart: number;
  bufferEnd: number;

  cfSim: SimulationState | null;
  cfSimId: string | null;
  cfWsConnected: boolean;
  cfError: string | null;
  runCounterfactual: (intervention: Intervention) => Promise<string | null>;
  discardCounterfactual: () => void;
  applyCounterfactual: () => Promise<void>;

  selectScenario: (id: string) => Promise<void>;
  selectVenue: (id: string) => void;
  runSimulation: () => Promise<void>;
  play: () => Promise<void>;
  pause: () => Promise<void>;
  reset: () => Promise<void>;
  step: (steps?: number) => Promise<void>;
  setSpeed: (speed: number) => Promise<void>;
  setEmergency: (active: boolean) => Promise<void>;
  jumpToMinute: (minute: number) => Promise<void>;
  optimize: () => Promise<void>;
  applyIntervention: (intervention: Intervention) => Promise<void>;
  refreshCatalog: () => Promise<void>;
  clearSimulation: () => void;
  clearError: () => void;

  viewMode: ViewMode;
  setViewMode: (m: ViewMode) => void;
  selectedAgentId: number | null;
  setSelectedAgentId: (id: number | null) => void;

  simRef: React.RefObject<SimulationState | null>;
  cfSimRef: React.RefObject<SimulationState | null>;
  compareViewMode: CompareViewMode;
  setCompareViewMode: (m: CompareViewMode) => void;

  aiConfigured: boolean | null;
  aiProvider: string | null;
  aiBusy: boolean;
  aiIdeas: AiSuggestion[];
  aiExplanation: AiExplainResponse | null;
  aiError: string | null;
  checkAiStatus: () => Promise<void>;
  runAiSimulation: (query: string, delta?: ScenarioDelta) => Promise<boolean>;
  generateAiIdeas: () => Promise<void>;
  explainCurrent: () => Promise<void>;
}

const SimulationContext = createContext<SimulationContextValue | null>(null);

const MAX_FRAMES = 260;
const MIN_FRAME_STEP_MIN = 0.05;

function compactFrame(frame: SimulationState): PlaybackFrame {
  return {
    ...frame,
    t: frame.t_min,
    agents: frame.agents.map((a) => ({
      ...a,
      position: {
        x: Math.round(a.position.x * 10) / 10,
        y: Math.round(a.position.y * 10) / 10,
      },
    })),
  };
}

function applyTheme(theme: ThemeMode) {
  document.documentElement.classList.toggle('dark', theme === 'dark');
  document.documentElement.style.colorScheme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', theme === 'dark' ? '#0a0c0e' : '#eef0f2');
}

export function SimulationProvider({ children }: { children: ReactNode }) {
  const [venues, setVenues] = useState<VenueModel[]>([]);
  const [scenarios, setScenarios] = useState<ScenarioModel[]>([]);
  const [venue, setVenue] = useState<VenueModel | null>(null);
  const [scenario, setScenario] = useState<ScenarioModel | null>(null);
  const [sim, setSim] = useState<SimulationState | null>(null);
  const [simId, setSimId] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [optimization, setOptimization] = useState<OptimizationResult | null>(null);
  const [optimizing, setOptimizing] = useState(false);
  const [theme, setTheme] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem('cf-theme');
    if (saved === 'dark' || saved === 'light') return saved;
    return 'dark';
  });
  const [guided, setGuided] = useState<GuidedStep>('idle');
  const [buffer, setBuffer] = useState<PlaybackFrame[]>([]);
  const [frameIndex, setFrameIndex] = useState(-1);
  const [seeking, setSeeking] = useState(false);
  const lastBufferedMin = useRef<number | null>(null);

  // AI natural-language interface
  const [aiConfigured, setAiConfigured] = useState<boolean | null>(null);
  const [aiProvider, setAiProvider] = useState<string | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiIdeas, setAiIdeas] = useState<AiSuggestion[]>([]);
  const [aiExplanation, setAiExplanation] = useState<AiExplainResponse | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);

  // counterfactual
  const [cfSim, setCfSim] = useState<SimulationState | null>(null);
  const [cfSimId, setCfSimId] = useState<string | null>(null);
  const [cfWsConnected, setCfWsConnected] = useState(false);
  const [cfError, setCfError] = useState<string | null>(null);
  const cfWsRef = useRef<WebSocket | null>(null);

  // view mode & agent selection
  const [viewMode, setViewMode] = useState<ViewMode>('command');
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  // simRef / cfSimRef — updated on every WS frame for rAF consumers
  const simRef = useRef<SimulationState | null>(null);
  const cfSimRef = useRef<SimulationState | null>(null);

  // 100 ms throttle: only call setSim at most 10× per second
  const lastReactUpdateMs = useRef<number>(0);
  const lastCfReactUpdateMs = useRef<number>(0);

  // compare view mode
  const [compareViewMode, setCompareViewMode] = useState<CompareViewMode>('counterfactual');

  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem('cf-theme', theme);
  }, [theme]);

  const toggleTheme = useCallback(
    () => setTheme((t) => (t === 'light' ? 'dark' : 'light')),
    [],
  );
  const dismissGuided = useCallback(() => setGuided((g) => (g === 'bottleneck' ? 'done' : g)), []);

  const fail = useCallback((e: unknown, fallback: string) => {
    setError(e instanceof Error ? e.message : fallback);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then(() => {
        if (!cancelled) setBackendOnline(true);
      })
      .catch(() => {
        if (!cancelled) setBackendOnline(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    void checkAiStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendOnline]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listVenues(), api.listScenarios()])
      .then(([v, s]) => {
        if (cancelled) return;
        setVenues(v);
        setScenarios(s);
        if (s.length > 0) {
          const def = s.find((sc) => sc.special?.default === true) ?? s[0];
          setScenario(def);
          const vv = v.find((x) => x.id === def.venue_id) ?? v[0] ?? null;
          setVenue(vv);
        }
      })
      .catch((e) => fail(e, 'Failed to load venues/scenarios'));
    return () => {
      cancelled = true;
    };
  }, [fail]);

  const refreshCatalog = useCallback(async () => {
    try {
      const [v, s] = await Promise.all([api.listVenues(), api.listScenarios()]);
      setVenues(v);
      setScenarios(s);
      setVenue((cur) => (cur ? (v.find((x) => x.id === cur.id) ?? v[0] ?? cur) : cur));
      setScenario((cur) => (cur ? (s.find((x) => x.id === cur.id) ?? s[0] ?? cur) : cur));
    } catch {
      /* keep current catalog */
    }
  }, []);

  const selectScenario = useCallback(
    async (id: string) => {
      const sc = scenarios.find((x) => x.id === id) ?? (await api.scenario(id));
      if (!sc) return;
      setScenario(sc);
      const v = venues.find((x) => x.id === sc.venue_id) ?? null;
      if (v) setVenue(v);
      else {
        try {
          setVenue(await api.venue(sc.venue_id));
        } catch (e) {
          fail(e, `Venue '${sc.venue_id}' not found`);
        }
      }
    },
    [scenarios, venues, fail],
  );

  const selectVenue = useCallback(
    (id: string) => {
      const v = venues.find((x) => x.id === id) ?? null;
      if (v) {
        setVenue(v);
        // switching venue invalidates any running simulation
        setSimId(null);
        setSim(null);
        setCfSimId(null);
        setCfSim(null);
        setOptimization(null);
        setBuffer([]);
        setFrameIndex(-1);
        setSeeking(false);
        lastBufferedMin.current = null;
        setGuided('idle');
      }
    },
    [venues],
  );

  // live WebSocket feed (main)
  useEffect(() => {
    if (!simId) {
      setWsConnected(false);
      setSim(null);
      return;
    }
    let disposed = false;
    const ws = new WebSocket(wsUrl(simId));
    wsRef.current = ws;
    setWsConnected(false);
    ws.onopen = () => {
      if (!disposed) setWsConnected(true);
    };
    ws.onmessage = (event) => {
      if (disposed) return;
      try {
        const state = JSON.parse(event.data as string) as SimulationState;
        if (!state || state.sim_id !== simId) return;

        // Update ref immediately on every frame (for rAF loop — no React overhead)
        simRef.current = state;

        // Throttle React state updates to max 10fps (100 ms between renders)
        const now = performance.now();
        if (now - lastReactUpdateMs.current >= 100) {
          lastReactUpdateMs.current = now;
          setSim(state);

          // record playback frame when live is advancing
          const t = state.t_min;
          const last = lastBufferedMin.current;
          if (last == null || t - last >= MIN_FRAME_STEP_MIN) {
            lastBufferedMin.current = t;
            setBuffer((prev) => {
              const next = [...prev, compactFrame(state)];
              return next.length > MAX_FRAMES ? next.slice(next.length - MAX_FRAMES) : next;
            });
          }
        }
      } catch {
        /* ignore malformed frame */
      }
    };
    ws.onclose = () => {
      if (!disposed) setWsConnected(false);
    };
    ws.onerror = () => {
      if (!disposed) setWsConnected(false);
    };
    return () => {
      disposed = true;
      ws.close();
      wsRef.current = null;
    };
  }, [simId]);

  // counterfactual WebSocket feed
  useEffect(() => {
    if (!cfSimId) {
      setCfWsConnected(false);
      setCfSim(null);
      return;
    }
    let disposed = false;
    const ws = new WebSocket(wsUrl(cfSimId));
    cfWsRef.current = ws;
    setCfWsConnected(false);
    ws.onopen = () => {
      if (!disposed) setCfWsConnected(true);
    };
    ws.onmessage = (event) => {
      if (disposed) return;
      try {
        const state = JSON.parse(event.data as string) as SimulationState;
        if (state && state.sim_id === cfSimId) {
          // Update ref immediately on every frame (for rAF loop)
          cfSimRef.current = state;

          // Throttle React state updates to max 10fps (100 ms between renders)
          const now = performance.now();
          if (now - lastCfReactUpdateMs.current >= 100) {
            lastCfReactUpdateMs.current = now;
            setCfSim(state);
          }
        }
      } catch {
        /* ignore malformed frame */
      }
    };
    ws.onclose = () => {
      if (!disposed) setCfWsConnected(false);
    };
    ws.onerror = () => {
      if (!disposed) setCfWsConnected(false);
    };
    return () => {
      disposed = true;
      ws.close();
      cfWsRef.current = null;
    };
  }, [cfSimId]);

  const runSimulation = useCallback(
    async (sc?: ScenarioModel) => {
      const target = sc ?? scenario;
      if (!target) {
        setError('Select a scenario first');
        return;
      }
      setBusy(true);
      setOptimization(null);
      discardCounterfactual();
      setBuffer([]);
      setFrameIndex(-1);
      lastBufferedMin.current = null;
      setGuided('running');
      try {
        const state = await api.runSimulation(target.id);
        setSim(state);
        setSimId(state.sim_id);
        setError(null);
      } catch (e) {
        fail(e, 'Failed to start simulation');
        setGuided('idle');
      } finally {
        setBusy(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scenario, fail],
  );

  const sendWs = useCallback(
    (action: string, value?: unknown, ws?: WebSocket | null) => {
      const target = ws ?? wsRef.current;
      if (target && target.readyState === WebSocket.OPEN) {
        target.send(JSON.stringify(value === undefined ? { action } : { action, ...value }));
        return true;
      }
      return false;
    },
    [],
  );

  const sendToAll = useCallback(
    (action: string, value?: unknown) => {
      const main = sendWs(action, value);
      const cf = cfSimId ? sendWs(action, value, cfWsRef.current) : false;
      return { main, cf };
    },
    [cfSimId, sendWs],
  );

  const play = useCallback(async () => {
    if (seeking) {
      setFrameIndex(-1);
      setSeeking(false);
    }
    const sent = sendToAll('play');
    if (!sent.main && simId) {
      const r = await api.playSimulation(simId);
      setSim((cur) => (cur ? { ...cur, status: r.status as SimulationState['status'] } : cur));
    }
  }, [seeking, sendToAll, simId]);

  const pause = useCallback(async () => {
    const sent = sendToAll('pause');
    if (!sent.main && simId) {
      const r = await api.pauseSimulation(simId);
      setSim((cur) => (cur ? { ...cur, status: r.status as SimulationState['status'] } : cur));
    }
  }, [sendToAll, simId]);

  const reset = useCallback(async () => {
    setFrameIndex(-1);
    setSeeking(false);
    setBuffer([]);
    lastBufferedMin.current = null;
    setGuided('running');
    const sent = sendToAll('reset');
    if (!sent.main && simId) await api.resetSimulation(simId);
  }, [sendToAll, simId]);

  const step = useCallback(
    async (steps = 1) => {
      if (seeking) {
        setFrameIndex(-1);
        setSeeking(false);
      }
      const sent = sendToAll('step', { value: steps });
      if (!sent.main && simId) await api.stepSimulation(simId, steps);
    },
    [seeking, sendToAll, simId],
  );

  const setSpeed = useCallback(
    async (speed: number) => {
      sendToAll('set_speed', { value: speed });
      if (simId) await api.setSpeed(simId, speed);
    },
    [sendToAll, simId],
  );

  const setEmergency = useCallback(
    async (active: boolean) => {
      const sent = sendToAll('emergency', { active });
      if (!sent.main && simId) await api.emergency(simId, active);
    },
    [sendToAll, simId],
  );

  const jumpToMinute = useCallback(
    async (minute: number) => {
      if (!simId) return;
      setSeeking(true);
      setFrameIndex(-1);
      setBuffer([]);
      lastBufferedMin.current = null;
      try {
        const nextState = await api.scrubSimulation(simId, minute);
        setSim(nextState);
      } catch (e) {
        fail(e, 'Scrub failed');
      } finally {
        setSeeking(false);
      }
    },
    [simId, fail],
  );

  const optimize = useCallback(async () => {
    if (!simId) return;
    setOptimizing(true);
    try {
      setOptimization(await api.optimize(simId));
      setError(null);
    } catch (e) {
      fail(e, 'Optimisation failed');
    } finally {
      setOptimizing(false);
    }
  }, [simId, fail]);

  const applyIntervention = useCallback(
    async (intervention: Intervention) => {
      if (!simId || sendWs('apply_intervention', { intervention })) {
        setOptimization(null);
        return;
      }
      await api.applyIntervention(simId, intervention);
      setOptimization(null);
    },
    [simId, sendWs],
  );

  // ------------------------------------------------------------------ //
  //  AI natural-language interface
  // ------------------------------------------------------------------ //
  const checkAiStatus = useCallback(async () => {
    try {
      const st: AiProviderStatus = await api.aiStatus();
      setAiConfigured(st.configured);
      setAiProvider(st.provider);
    } catch {
      setAiConfigured(false);
      setAiProvider(null);
    }
  }, []);

  const runAiSimulation = useCallback(
    async (query: string, delta?: ScenarioDelta): Promise<boolean> => {
      if (!scenario) {
        setError('Select a scenario first');
        return false;
      }
      setAiBusy(true);
      setAiError(null);
      setAiExplanation(null);
      setAiIdeas([]);
      try {
        const state = delta
          ? await api.aiSimulateDelta(scenario.id, delta)
          : await api.aiSimulate(query, scenario.id);
        setSim(state);
        setSimId(state.sim_id);
        setOptimization(null);
        discardCounterfactual();
        setBuffer([]);
        setFrameIndex(-1);
        lastBufferedMin.current = null;
        setGuided('running');
        setError(null);
        setAiConfigured(true);
        return true;
      } catch (e) {
        setAiError(e instanceof Error ? e.message : 'AI request failed');
        setGuided('idle');
        return false;
      } finally {
        setAiBusy(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scenario, fail],
  );

  const generateAiIdeas = useCallback(async () => {
    if (!scenario) return;
    setAiBusy(true);
    setAiError(null);
    try {
      const res = await api.aiSuggest(scenario.id);
      setAiIdeas(res.suggestions);
      setAiConfigured(true);
    } catch (e) {
      setAiError(e instanceof Error ? e.message : 'Suggestions failed');
    } finally {
      setAiBusy(false);
    }
  }, [scenario]);

  const explainCurrent = useCallback(async () => {
    if (!simId) {
      setAiError('Start a simulation first');
      return;
    }
    setAiBusy(true);
    setAiError(null);
    try {
      setAiExplanation(await api.aiExplain(simId));
      setAiConfigured(true);
    } catch (e) {
      setAiError(e instanceof Error ? e.message : 'Explanation failed');
    } finally {
      setAiBusy(false);
    }
  }, [simId]);

  // ------------------------------------------------------------------ //
  //  Counterfactual
  // ------------------------------------------------------------------ //
  const runCounterfactual = useCallback(
    async (intervention: Intervention): Promise<string | null> => {
      if (!simId) return null;
      setCfError(null);
      try {
        const state = await api.counterfactual(simId, intervention);
        setCfSimId(state.sim_id);
        setCfSim(state);
        setGuided('done');
        return state.sim_id;
      } catch (e) {
        setCfError(e instanceof Error ? e.message : 'Counterfactual failed');
        return null;
      }
    },
    [simId],
  );

  const discardCounterfactual = useCallback(() => {
    setCfSimId(null);
    setCfSim(null);
    setCfError(null);
  }, []);

  const applyCounterfactual = useCallback(async () => {
    if (!simId || cfError) return;
    const sent = sendWs('apply_intervention', { intervention: { parameters: {} } });
    void sent;
    discardCounterfactual();
  }, [simId, cfError, sendWs, discardCounterfactual]);

  const seekFrame = useCallback((i: number) => {
    setFrameIndex(i);
    setSeeking(true);
  }, []);
  const resumeLive = useCallback(() => {
    setFrameIndex(-1);
    setSeeking(false);
  }, []);

  const bufferStart = buffer.length > 0 ? buffer[0].t : 0;
  const bufferEnd = buffer.length > 0 ? buffer[buffer.length - 1].t : 0;
  const displayedSim =
    frameIndex >= 0 && buffer[frameIndex] ? buffer[frameIndex] : sim;

  const clearSimulation = useCallback(() => {
    setSimId(null);
    setSim(null);
    setCfSimId(null);
    setCfSim(null);
    setOptimization(null);
    setBuffer([]);
    setFrameIndex(-1);
    setSeeking(false);
    lastBufferedMin.current = null;
    setGuided('idle');
  }, []);

  const clearError = useCallback(() => setError(null), []);

  const value = useMemo<SimulationContextValue>(
    () => ({
      backendOnline,
      venues,
      scenarios,
      venue,
      scenario,
      sim,
      simId,
      wsConnected,
      busy,
      error,
      optimization,
      optimizing,
      theme,
      toggleTheme,
      guided,
      dismissGuided,
      buffer,
      frameIndex,
      seeking,
      seekFrame,
      resumeLive,
      displayedSim,
      bufferStart,
      bufferEnd,
      cfSim,
      cfSimId,
      cfWsConnected,
      cfError,
      runCounterfactual,
      discardCounterfactual,
      applyCounterfactual,
      selectScenario,
      selectVenue,
      runSimulation,
      play,
      pause,
      reset,
      step,
      setSpeed,
      setEmergency,
      jumpToMinute,
      optimize,
      applyIntervention,
      refreshCatalog,
      clearSimulation,
      clearError,
      viewMode,
      setViewMode,
      selectedAgentId,
      setSelectedAgentId,
      simRef,
      cfSimRef,
      compareViewMode,
      setCompareViewMode,
      aiConfigured,
      aiProvider,
      aiBusy,
      aiIdeas,
      aiExplanation,
      aiError,
      checkAiStatus,
      runAiSimulation,
      generateAiIdeas,
      explainCurrent,
    }),
    [
      backendOnline, venues, scenarios, venue, scenario, sim, simId, wsConnected, busy, error,
      optimization, optimizing, theme, toggleTheme, guided, dismissGuided, buffer, frameIndex,
      seeking, seekFrame, resumeLive, displayedSim, bufferStart, bufferEnd, cfSim, cfSimId,
      cfWsConnected, cfError, runCounterfactual, discardCounterfactual, applyCounterfactual,
      selectScenario, selectVenue, runSimulation, play, pause, reset, step, setSpeed, setEmergency,
      jumpToMinute, optimize, applyIntervention, refreshCatalog, clearSimulation, clearError,
      aiConfigured, aiProvider, aiBusy, aiIdeas, aiExplanation, aiError, checkAiStatus,
      runAiSimulation, generateAiIdeas, explainCurrent,
      viewMode, setViewMode, selectedAgentId, setSelectedAgentId,
      simRef, cfSimRef, compareViewMode, setCompareViewMode,
    ],
  );

  return <SimulationContext.Provider value={value}>{children}</SimulationContext.Provider>;
}

export function useSimulation(): SimulationContextValue {
  const ctx = useContext(SimulationContext);
  if (!ctx) throw new Error('useSimulation must be used within SimulationProvider');
  return ctx;
}