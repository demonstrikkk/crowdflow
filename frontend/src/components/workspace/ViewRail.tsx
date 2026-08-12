import type { ViewMode } from '../../lib/types';

const VIEWS: { id: ViewMode; label: string; icon: string; group: string }[] = [
  { id: 'command',        label: 'Command',      icon: '⌘',  group: 'observe' },
  { id: 'stadium',        label: 'Stadium',      icon: '🏟', group: 'observe' },
  { id: 'crowd',          label: 'Crowd',        icon: '👥', group: 'observe' },
  { id: 'agent',          label: 'Agent',        icon: '🎯', group: 'observe' },
  { id: 'security',       label: 'Security',     icon: '📷', group: 'observe' },
  { id: 'density',        label: 'Density',      icon: '🌡', group: 'analyse' },
  { id: 'flow',           label: 'Flow Field',   icon: '→',  group: 'analyse' },
  { id: 'route',          label: 'Route',        icon: '🛤', group: 'analyse' },
  { id: 'emergency',      label: 'Emergency',    icon: '🚨', group: 'analyse' },
  { id: 'weather',        label: 'Weather',      icon: '🌤', group: 'analyse' },
  { id: 'behaviour',      label: 'Behaviour',    icon: '🧠', group: 'analyse' },
  { id: 'infrastructure', label: 'Infra',        icon: '🏗', group: 'analyse' },
  { id: 'replay',         label: 'Replay',       icon: '⏮', group: 'time' },
  { id: 'compare',        label: 'Compare',      icon: '⚡', group: 'time' },
];

const GROUP_LABELS: Record<string, string> = {
  observe: 'OBSERVE',
  analyse: 'ANALYSE',
  time:    'TIME',
};

export function ViewRail({
  viewMode,
  onChange,
}: {
  viewMode: ViewMode;
  onChange: (v: ViewMode) => void;
}) {
  const groups = ['observe', 'analyse', 'time'];
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        padding: '8px 4px',
        background: 'var(--od-panel)',
        borderRight: '1px solid var(--od-line)',
        minWidth: 60,
        maxWidth: 60,
        overflowY: 'auto',
        overflowX: 'hidden',
        flexShrink: 0,
      }}
    >
      {groups.map((grp) => (
        <div key={grp}>
          <div
            style={{
              fontSize: 7,
              letterSpacing: '0.16em',
              color: 'var(--od-muted)',
              padding: '6px 2px 2px',
              fontWeight: 700,
              textAlign: 'center',
            }}
          >
            {GROUP_LABELS[grp]}
          </div>
          {VIEWS.filter((v) => v.group === grp).map((v) => (
            <button
              key={v.id}
              onClick={() => onChange(v.id)}
              title={v.label}
              aria-pressed={viewMode === v.id}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 2,
                padding: '5px 2px',
                borderRadius: 6,
                border: viewMode === v.id
                  ? '1px solid var(--od-accent)'
                  : '1px solid transparent',
                cursor: 'pointer',
                background: viewMode === v.id
                  ? 'var(--od-accent)'
                  : 'transparent',
                color: viewMode === v.id ? '#fff' : 'var(--od-muted)',
                fontSize: 14,
                width: '100%',
                transition: 'all 0.12s',
              }}
            >
              <span aria-hidden>{v.icon}</span>
              <span style={{
                fontSize: 7,
                letterSpacing: '0.08em',
                fontWeight: 700,
                lineHeight: 1,
                whiteSpace: 'nowrap',
              }}>
                {v.label.toUpperCase().slice(0, 6)}
              </span>
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}
