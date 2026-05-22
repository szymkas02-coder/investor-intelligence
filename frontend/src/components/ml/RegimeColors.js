export const REGIME_COLORS = {
  bull:          '#22c55e',
  consolidation: '#3b82f6',
  stagflation:   '#f97316',
  bear:          '#ef4444',
  unknown:       '#6b7280',
}

export const REGIME_LABELS_PL = {
  bull:          'Hossa',
  consolidation: 'Konsolidacja',
  stagflation:   'Drogie akcje',
  bear:          'Bessa',
}

export const REGIME_LABELS_EN = {
  bull:          'Bull',
  consolidation: 'Consolidation',
  stagflation:   'Expensive',
  bear:          'Bear',
}

export function regimeColor(state) {
  return REGIME_COLORS[state] ?? REGIME_COLORS.unknown
}
