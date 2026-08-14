import type { Intervention, OptimizationCandidate } from './types';

export function interventionTitle(iv: Intervention): string {
  const p = iv.parameters ?? {};
  const gate = String(p.gate ?? p.from ?? '').replace('GATE_', '');
  const to = String(p.to ?? '').replace('GATE_', '');
  const cap = p.capacity != null ? Number(p.capacity) : null;
  switch (iv.type) {
    case 'CHANGE_GATE':
      if (!gate) return 'Change gate capacity';
      if (cap === 0) return `Close Gate ${gate}`;
      return cap != null && cap > 0 ? `Restrict Gate ${gate} → ${cap}/min` : `Open Gate ${gate}`;
    case 'REDIRECT':
      return gate && to ? `Redirect ${p.percent ?? 15}% Gate ${gate} → ${to}` : iv.description;
    case 'CLOSE_CORRIDOR':
      return `Close corridor ${String(p.edge ?? p.external_edge ?? '').split('→').join(' → ')}`;
    case 'OPEN_CORRIDOR':
      return `Reopen ${String(p.edge ?? p.external_edge ?? '').split('→').join(' → ')}`;
    case 'INCREASE_CAPACITY':
      return `Raise capacity ${String(p.node ?? p.edge ?? '').replace(/_/g, ' ')}`;
    default:
      return iv.description || iv.type;
  }
}

export type ImpactRow = { label: string; value: string; good: boolean };

export function impactRows(cand: OptimizationCandidate): ImpactRow[] {
  const imp = cand.improvement ?? {};
  const rows: ImpactRow[] = [];
  const add = (label: string, v: number | undefined, unit = '', fmtV?: (x: number) => number) => {
    if (v == null || v === 0) return;
    const shown = fmtV ? fmtV(v) : Math.round(v);
    rows.push({
      label,
      value: `${v > 0 ? '+' : ''}${shown}${unit}`,
      good: v < 0, // every improvement field: negative = better
    });
  };
  add('Critical zones', imp.critical_zones);
  add('Max queue', imp.max_queue, ' ppl');
  add('Avg travel', imp.avg_travel_time_min, ' min', (x) => +x.toFixed(1));
  add('Peak density', imp.peak_density, '', (x) => +x.toFixed(3));
  add('Peak utilisation', imp.max_utilisation, '', (x) => +((x * 100).toFixed(0)));
  const cr = cand.candidate_metrics.risk_level;
  const br = cand.baseline_metrics.risk_level;
  if (cr && br && cr !== br) rows.push({ label: 'Risk', value: `${br} → ${cr}`, good: true });
  return rows;
}