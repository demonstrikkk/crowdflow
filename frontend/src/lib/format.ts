import type { RiskLevel } from './types';

export const RISK_COLORS: Record<RiskLevel, string> = {
  NORMAL: 'var(--od-ink)',
  ELEVATED: 'var(--od-warn)',
  HIGH: 'var(--od-danger)',
  CRITICAL: 'var(--od-danger)',
};

export const RISK_ORDER: Record<RiskLevel, number> = {
  NORMAL: 0,
  ELEVATED: 1,
  HIGH: 2,
  CRITICAL: 3,
};

export function riskColor(risk: RiskLevel): string {
  return RISK_COLORS[risk] ?? RISK_COLORS.NORMAL;
}

export function riskClass(risk: RiskLevel): string {
  switch (risk) {
    case 'NORMAL':
      return 'risk-normal';
    case 'ELEVATED':
      return 'risk-elevated';
    case 'HIGH':
      return 'risk-high';
    case 'CRITICAL':
      return 'risk-critical';
  }
}

export function fmtInt(n: number): string {
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(n);
}

export function fmtPct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export function fmtNum(v: number, digits = 1): string {
  if (!Number.isFinite(v)) return '—';
  return v.toFixed(digits);
}

export function fmtDuration(min: number | null | undefined): string {
  if (min == null || !Number.isFinite(min)) return '—';
  const m = Math.floor(min);
  const s = Math.round((min - m) * 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function fmtClock(min: number): string {
  const h = Math.floor(min / 60);
  const m = Math.floor(min % 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

export function fmtSpeed(mps: number): string {
  return `${fmtNum(mps, 2)} m/s`;
}

export function trendGlyph(trend: string): string {
  const t = trend.toLowerCase();
  if (t.includes('rising') || t.includes('growing') || t.includes('increas')) return '▲';
  if (t.includes('falling') || t.includes('decreas')) return '▼';
  return '▶';
}

export function trendClass(trend: string): string {
  const t = trend.toLowerCase();
  if (t.includes('rising') || t.includes('growing') || t.includes('increas')) return 'text-error';
  if (t.includes('falling') || t.includes('decreas')) return 'text-secondary';
  return 'text-secondary';
}

export function riskState(risk: RiskLevel): 'ok' | 'warn' | 'danger' {
  switch (risk) {
    case 'NORMAL':
      return 'ok';
    case 'ELEVATED':
      return 'warn';
    default:
      return 'danger';
  }
}

/** Live element colour inside the venue canvas (density is scaled, never gradient-banded). */
export function elementColor(
  risk: RiskLevel,
  utilisation: number,
): string {
  if (risk === 'CRITICAL' || risk === 'HIGH') return 'var(--od-danger)';
  if (risk === 'ELEVATED') return 'var(--od-warn)';
  return utilisation > 0.85 ? 'var(--od-ok)' : 'var(--od-ink)';
}