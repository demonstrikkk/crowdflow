import type { WeatherModel, SimulationMetrics } from '../../lib/types';

function Gauge({
  label,
  value,
  max = 1,
  unit = '%',
  warn = 0.6,
  crit = 0.8,
  invert = false,
}: {
  label: string;
  value: number;
  max?: number;
  unit?: string;
  warn?: number;
  crit?: number;
  invert?: boolean;
}) {
  const pct = Math.min(1, Math.max(0, value / max));
  const effective = invert ? 1 - pct : pct;
  const color =
    effective >= crit
      ? 'var(--od-danger, #ef4444)'
      : effective >= warn
      ? 'var(--od-warn, #f59e0b)'
      : 'var(--od-ok, #22c55e)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 9 }}>
      <div style={{ color: 'var(--od-muted)', width: 84, flexShrink: 0 }}>
        {label}
      </div>
      <div
        style={{
          flex: 1,
          height: 4,
          background: 'var(--od-canvas)',
          borderRadius: 2,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${pct * 100}%`,
            height: '100%',
            background: color,
            borderRadius: 2,
            transition: 'width 0.5s',
          }}
        />
      </div>
      <div
        style={{
          color: 'var(--od-ink)',
          width: 44,
          textAlign: 'right',
          fontWeight: 700,
        }}
      >
        {unit === '%'
          ? `${(value * 100).toFixed(0)}%`
          : `${value.toFixed(unit === '°C' ? 0 : 1)}${unit}`}
      </div>
    </div>
  );
}

export function WeatherPanel({
  weather,
  metrics,
}: {
  weather: WeatherModel;
  metrics: SimulationMetrics;
}) {
  const conditionEmoji: Record<string, string> = {
    CLEAR: '☀️',
    HEAT: '🔥',
    HEAVY_RAIN: '🌧️',
    RAIN: '🌦️',
    STORM: '⛈️',
    HAIL: '🌨️',
    FOG: '🌫️',
  };
  const emoji = conditionEmoji[weather.condition] ?? '🌡️';
  return (
    <div
      style={{
        background: 'var(--od-panel)',
        border: '1px solid var(--od-line)',
        borderRadius: 8,
        padding: 14,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 24 }} aria-hidden>
          {emoji}
        </span>
        <div>
          <div
            style={{
              fontSize: 20,
              fontWeight: 800,
              color: 'var(--od-ink)',
              lineHeight: 1,
            }}
          >
            {weather.temperature.toFixed(0)}°C
          </div>
          <div
            style={{
              fontSize: 8,
              letterSpacing: '0.12em',
              color: 'var(--od-muted)',
              textTransform: 'uppercase',
              fontWeight: 700,
              marginTop: 2,
            }}
          >
            {weather.condition.replace('_', ' ')}
          </div>
        </div>
        <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
          <div style={{ fontSize: 9, color: 'var(--od-muted)' }}>
            Heat Index
          </div>
          <div
            style={{
              fontSize: 14,
              fontWeight: 700,
              color:
                weather.heat_index >= 38
                  ? 'var(--od-danger)'
                  : 'var(--od-ink)',
            }}
          >
            {weather.heat_index.toFixed(0)}°C
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        <Gauge
          label="Temperature"
          value={weather.temperature}
          max={50}
          unit="°C"
          warn={32 / 50}
          crit={40 / 50}
        />
        <Gauge
          label="Humidity"
          value={weather.humidity}
          max={1}
          unit="%"
          warn={0.7}
          crit={0.88}
        />
        <Gauge
          label="UV Index"
          value={weather.uv_index}
          max={12}
          unit=" UV"
          warn={6 / 12}
          crit={9 / 12}
        />
        <Gauge
          label="Wind"
          value={weather.wind_speed_mps}
          max={25}
          unit=" m/s"
          warn={10 / 25}
          crit={18 / 25}
        />
        <Gauge
          label="Visibility"
          value={weather.visibility}
          max={1}
          unit="%"
          invert
          warn={0.3}
          crit={0.6}
        />
      </div>

      {metrics.water_seekers > 0 && (
        <div
          style={{
            background: 'rgba(239,68,68,0.1)',
            border: '1px solid var(--od-danger)',
            borderRadius: 6,
            padding: '6px 10px',
            fontSize: 9,
            color: 'var(--od-danger)',
            fontWeight: 700,
          }}
        >
          💧 {metrics.water_seekers} agents actively seeking water stations.
        </div>
      )}

      <div
        style={{
          borderTop: '1px solid var(--od-line)',
          paddingTop: 10,
          display: 'flex',
          flexDirection: 'column',
          gap: 5,
        }}
      >
        <div
          style={{
            fontSize: 8,
            letterSpacing: '0.12em',
            color: 'var(--od-muted)',
            fontWeight: 700,
            textTransform: 'uppercase',
            marginBottom: 2,
          }}
        >
          Crowd Physiological Aggregates
        </div>
        <Gauge
          label="Avg Crowd Stress"
          value={metrics.avg_stress}
          warn={0.45}
          crit={0.7}
        />
        <Gauge
          label="Avg Fatigue"
          value={metrics.avg_fatigue}
          warn={0.4}
          crit={0.65}
        />
        <Gauge
          label="Avg Patience"
          value={metrics.avg_patience}
          invert
          warn={0.4}
          crit={0.6}
        />
        <Gauge
          label="Avg Hydration"
          value={metrics.avg_hydration}
          invert
          warn={0.35}
          crit={0.55}
        />
      </div>
    </div>
  );
}
