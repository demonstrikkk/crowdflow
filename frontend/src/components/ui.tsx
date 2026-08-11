import type { ReactNode } from 'react';
import { riskClass } from '../lib/format';
import type { RiskLevel } from '../lib/types';

export function Panel({
  title,
  code,
  right,
  children,
  className = '',
}: {
  title: string;
  code?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`border border-outline-variant bg-surface-container-lowest ${className}`}>
      <div className="flex items-center justify-between gap-md px-md py-sm grid-line-bottom bg-surface-container-low">
        <h2 className="text-[11px] font-bold uppercase tracking-[0.22em]">{title}</h2>
        <div className="flex items-center gap-md">
          {right}
          {code && <span className="text-[9px] uppercase tracking-widest text-secondary">{code}</span>}
        </div>
      </div>
      {children}
    </section>
  );
}

export function CellLabel({ children }: { children: ReactNode }) {
  return (
    <span className="text-[10px] uppercase tracking-[0.2em] text-secondary grid-line-right px-md py-sm h-full inline-flex items-center">
      {children}
    </span>
  );
}

export function RiskBadge({ risk, compact = false }: { risk: RiskLevel; compact?: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-xs uppercase font-bold tracking-[0.18em] ${riskClass(risk)} ${
        compact ? 'text-[9px] px-xs py-[2px]' : 'text-[10px] px-sm py-xs border'
      }`}
      style={{ borderColor: 'currentColor' }}
    >
      {risk}
    </span>
  );
}

export function StatCell({
  label,
  value,
  sub,
  tone = 'default',
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: 'default' | 'good' | 'bad' | 'alert';
}) {
  const toneClass =
    tone === 'good'
      ? 'text-secondary'
      : tone === 'bad' || tone === 'alert'
        ? 'text-error'
        : 'text-primary';
  return (
    <div className="flex flex-col gap-xs px-md py-md">
      <span className="text-[10px] uppercase tracking-[0.2em] text-secondary">{label}</span>
      <span className={`text-headline-lg font-headline-lg font-extrabold leading-none ${toneClass}`}>
        {value}
      </span>
      {sub && <span className="text-[10px] uppercase tracking-widest text-secondary">{sub}</span>}
    </div>
  );
}

export function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-sm cursor-pointer select-none text-[10px] uppercase tracking-[0.18em] font-bold">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="w-3.5 h-3.5 accent-black cursor-pointer"
      />
      {label}
    </label>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-md p-xl text-center">
      <span className="text-headline-lg font-display-xl font-extrabold uppercase tracking-tighter text-2xl">
        {title}
      </span>
      {hint && <span className="text-[11px] uppercase tracking-[0.18em] text-secondary">{hint}</span>}
    </div>
  );
}