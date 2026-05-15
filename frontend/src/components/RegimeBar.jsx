import { useTranslation } from 'react-i18next'

const COLORS = {
  bull:          '#22c55e',
  consolidation: '#3b82f6',
  stagflation:   '#f97316',
  bear:          '#ef4444',
}

export default function RegimeBar({ probBull, probBear, probConsolidation, probStagflation }) {
  const { t } = useTranslation()

  const segments = [
    { label: t('signals.bull'),          value: probBull ?? 0,          key: 'bull' },
    { label: t('signals.consolidation'), value: probConsolidation ?? 0, key: 'consolidation' },
    { label: t('signals.stagflation'),   value: probStagflation ?? 0,   key: 'stagflation' },
    { label: t('signals.bear'),          value: probBear ?? 0,          key: 'bear' },
  ]

  return (
    <div style={{ marginTop: '0.75rem' }}>
      <div style={{ display: 'flex', height: 24, borderRadius: 4, overflow: 'hidden' }}>
        {segments.map(s => (
          <div key={s.key}
               title={`${s.label}: ${(s.value * 100).toFixed(1)}%`}
               style={{ width: `${s.value * 100}%`, background: COLORS[s.key] }} />
        ))}
      </div>
      <div style={{ display: 'flex', gap: '1rem', marginTop: '0.4rem', fontSize: '0.75rem' }}>
        {segments.map(s => (
          <span key={s.key}>
            <span style={{ color: COLORS[s.key] }}>■</span>
            {' '}{s.label} {(s.value * 100).toFixed(0)}%
          </span>
        ))}
      </div>
    </div>
  )
}
