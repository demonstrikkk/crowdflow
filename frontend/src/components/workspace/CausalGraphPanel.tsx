import type { CausalGraph } from '../../lib/types';

const STATE_COLORS: Record<string, string> = {
  NORMAL:   'var(--od-ok,   #22c55e)',
  WARNING:  'var(--od-warn, #f59e0b)',
  CRITICAL: 'var(--od-danger, #ef4444)',
};

export function CausalGraphPanel({ graph }: { graph: CausalGraph }) {
  if (!graph.nodes.length) return null;

  return (
    <div
      style={{
        background: 'var(--od-panel)',
        border: '1px solid var(--od-line)',
        borderRadius: 8,
        padding: '12px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}
    >
      <div
        style={{
          fontSize: 9,
          letterSpacing: '0.2em',
          fontWeight: 800,
          color: 'var(--od-muted)',
          textTransform: 'uppercase',
          marginBottom: 2,
        }}
      >
        Causal Analysis
      </div>

      {graph.nodes.map((node) => {
        const incomingLinks = graph.links.filter((l) => l.target === node.id);
        const color = STATE_COLORS[node.state] ?? 'var(--od-muted)';
        return (
          <div key={node.id}>
            {incomingLinks.map((link) => (
              <div
                key={`${link.source}->${link.target}`}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  marginBottom: 2,
                  paddingLeft: 10,
                  opacity: 0.65,
                }}
              >
                <div
                  style={{
                    width: 1,
                    height: 12,
                    background: 'var(--od-line)',
                    flexShrink: 0,
                  }}
                />
                <span
                  style={{
                    fontSize: 8,
                    color: 'var(--od-muted)',
                    letterSpacing: '0.08em',
                    fontStyle: 'italic',
                  }}
                >
                  {link.label ?? '↓'}
                </span>
              </div>
            ))}

            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '5px 8px',
                borderRadius: 5,
                background: 'var(--od-canvas)',
                border: `1px solid ${color}`,
              }}
            >
              <div
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: color,
                  flexShrink: 0,
                  boxShadow: node.state === 'CRITICAL' ? `0 0 6px ${color}` : undefined,
                }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    color: 'var(--od-ink)',
                    letterSpacing: '0.04em',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {node.label}
                </div>
                <div
                  style={{
                    fontSize: 9,
                    color: 'var(--od-muted)',
                    marginTop: 1,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {node.value}
                </div>
              </div>
              <div
                style={{
                  fontSize: 8,
                  color,
                  fontWeight: 800,
                  letterSpacing: '0.1em',
                  flexShrink: 0,
                }}
              >
                {node.state}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
