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
  const row = (label: string, children: React.ReactNode) => (
    <div className="flex items-center justify-between gap-4 border-b border-od-line py-3">
      <span className="text-[10px] uppercase tracking-[0.2em] text-od-muted">{label}</span>
      {children}
    </div>
  );
  return (
    <div className="flex h-full flex-col bg-od-canvas">
      <div className="flex items-center justify-between border-b border-od-line bg-od-panel px-4 py-3">
        <h2 className="font-display text-[13px] font-bold uppercase tracking-[0.24em] text-od-ink">Settings</h2>
      </div>
      <div className="mx-auto w-full max-w-xl flex-1 overflow-y-auto px-4 py-6">
        <div className="border border-od-line bg-od-panel px-4">
          {row('Interface theme', (
            <button className="btn btn-ghost" onClick={onToggleTheme}>
              {theme === 'dark' ? 'DARK' : 'LIGHT'} →
            </button>
          ))}
          {row('Backend', (
            <span className="inline-flex items-center gap-2 text-[10px] uppercase tracking-[0.16em] text-od-muted">
              <span className={`status-dot ${backendOnline === false ? 'is-danger' : backendOnline ? 'is-ok' : 'is-scan'}`} />
              {backendOnline === false ? 'offline' : backendOnline ? 'live' : 'scanning'}
            </span>
          ))}
          {row('Venues', <button className="btn btn-ghost" onClick={() => go('venues')}>MANAGE</button>)}
          {row('Scenarios', <button className="btn btn-ghost" onClick={() => go('scenarios')}>MANAGE</button>)}
        </div>
        <p className="mt-6 text-center text-[10px] uppercase tracking-[0.2em] text-od-muted">
          CrowdFlow · crowd operations instrument · v2
        </p>
      </div>
    </div>
  );
}