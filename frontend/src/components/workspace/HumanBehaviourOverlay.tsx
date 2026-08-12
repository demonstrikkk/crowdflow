export type BehaviourField =
  | 'stress'
  | 'excitement'
  | 'fatigue'
  | 'patience'
  | 'hydration'
  | 'heat_exposure';

const FIELD_LABELS: Record<BehaviourField, string> = {
  stress: 'Stress',
  excitement: 'Excitement',
  fatigue: 'Fatigue',
  patience: 'Patience',
  hydration: 'Hydration',
  heat_exposure: 'Heat Exposure',
};

export function HumanBehaviourOverlay({
  field,
  onFieldChange,
}: {
  field: BehaviourField;
  onFieldChange: (f: BehaviourField) => void;
}) {
  return (
    <div
      style={{
        position: 'absolute',
        top: 10,
        right: 10,
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        zIndex: 10,
      }}
    >
      <div
        style={{
          background: 'var(--od-panel)',
          border: '1px solid var(--od-line)',
          borderRadius: 8,
          padding: 8,
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
          minWidth: 120,
        }}
      >
        <div
          style={{
            fontSize: 7,
            letterSpacing: '0.12em',
            color: 'var(--od-muted)',
            fontWeight: 700,
            textTransform: 'uppercase',
            padding: '2px 4px',
          }}
        >
          Behaviour Mode
        </div>
        {(Object.keys(FIELD_LABELS) as BehaviourField[]).map((f) => (
          <button
            key={f}
            onClick={() => onFieldChange(f)}
            style={{
              padding: '4px 6px',
              borderRadius: 4,
              border: 'none',
              background: field === f ? 'var(--od-accent)' : 'transparent',
              color: field === f ? '#fff' : 'var(--od-muted)',
              fontSize: 9,
              fontWeight: field === f ? 700 : 400,
              cursor: 'pointer',
              textAlign: 'left',
              textTransform: 'uppercase',
            }}
          >
            {FIELD_LABELS[f]}
          </button>
        ))}
      </div>
      <div
        style={{
          background: 'var(--od-panel)',
          border: '1px solid var(--od-line)',
          borderRadius: 8,
          padding: '8px 10px',
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
        }}
      >
        <div
          style={{
            fontSize: 7,
            letterSpacing: '0.12em',
            color: 'var(--od-muted)',
            fontWeight: 700,
          }}
        >
          LEGEND
        </div>
        {[
          ['Low / Normal', 'var(--od-ok, #22c55e)'],
          ['Elevated', 'var(--od-warn, #f59e0b)'],
          ['Critical', 'var(--od-danger, #ef4444)'],
        ].map(([label, color]) => (
          <div
            key={label}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: 2,
                background: color,
              }}
            />
            <span style={{ fontSize: 9, color: 'var(--od-muted)' }}>
              {label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
