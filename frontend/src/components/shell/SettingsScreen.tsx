import { useSimulation } from '../../store/SimulationContext';
import type { WorkspaceView } from '../../lib/selection';

export default function SettingsScreen({
  theme,
  onToggleTheme,
  backendOnline,
  go,
}: {
  theme: 'light' | 'dark';
  onToggleTheme: () => void;
  backendOnline: boolean | null;
  go: (v: WorkspaceView) => void;
}) {
  const { venues, scenarios, aiProvider } = useSimulation();
  const row = (label: string, children: React.ReactNode) => (
    <div className="flex items-center justify-between gap-4 border-b border-od-line py-3 last:border-0">
      <span className="sec-label">{label}</span>
      {children}
    </div>
  );
  return (
    <div className="flex h-full flex-col bg-od-canvas">
      <div className="flex shrink-0 items-center justify-between border-b border-od-line bg-od-panel px-4 py-3">
        <div>
          <h2 className="font-display text-[15px] font-bold uppercase tracking-[0.18em] text-od-ink leading-none">
            Settings
          </h2>
          <p className="mt-1 text-[9px] uppercase tracking-[0.24em] text-od-muted">Instrument configuration</p>
        </div>
        <span className="chip">
          <span className={`status-dot ${backendOnline === false ? 'is-danger' : backendOnline ? 'is-ok' : 'is-scan'}`} />
          {backendOnline === false ? 'offline' : backendOnline ? 'live' : 'scanning'}
        </span>
      </div>

      <div className="mx-auto w-full max-w-xl flex-1 overflow-y-auto px-4 py-6 scrollbar-thin">
        <div className="space-y-6">
          <div className="blk px-4">
            <div className="blk-hd !px-0">
              <span className="sec-label">Interface</span>
            </div>
            {row('Theme', (
              <button className="btn btn-ghost" onClick={onToggleTheme}>
                {theme === 'dark' ? 'DARK' : 'LIGHT'} →
              </button>
            ))}
          </div>

          <div className="blk px-4">
            <div className="blk-hd !px-0">
              <span className="sec-label">Catalogue</span>
            </div>
            {row('Venues', (
              <div className="flex items-center gap-3">
                <span className="num text-od-ink">{venues.length}</span>
                <button className="btn btn-ghost" onClick={() => go('venues')}>MANAGE</button>
              </div>
            ))}
            {row('Scenarios', (
              <div className="flex items-center gap-3">
                <span className="num text-od-ink">{scenarios.length}</span>
                <button className="btn btn-ghost" onClick={() => go('scenarios')}>MANAGE</button>
              </div>
            ))}
          </div>

          <div className="blk px-4">
            <div className="blk-hd !px-0">
              <span className="sec-label">Runtime</span>
            </div>
            {row('Backend', (
              <span className="inline-flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] text-od-muted">
                <span className={`status-dot ${backendOnline === false ? 'is-danger' : backendOnline ? 'is-ok' : 'is-scan'}`} />
                {backendOnline === false ? 'offline' : backendOnline ? 'live' : 'scanning'}
              </span>
            ))}
            {row('AI provider', (
              <span className="text-[10px] uppercase tracking-[0.14em] text-od-muted">{aiProvider ?? '—'}</span>
            ))}
          </div>
        </div>

        <p className="mt-8 text-center text-[10px] uppercase tracking-[0.2em] text-od-muted">
          CrowdFlow · crowd operations instrument · v2
        </p>
      </div>
    </div>
  );
}
