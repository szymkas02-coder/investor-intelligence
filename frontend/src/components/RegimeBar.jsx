import { useTranslation } from 'react-i18next'

const COLORS = {
  risk_on:     '#22c55e',
  stagflation: '#f97316',
  risk_off:    '#ef4444',
  deflation:   '#a855f7',
}

export default function RegimeBar({ probRiskOn, probRiskOff, probStagflation, probDeflation }) {
  const { t } = useTranslation()

  const segments = [
    { label: t('signals.riskOn'),     value: probRiskOn,     key: 'risk_on' },
    { label: t('signals.stagflation'), value: probStagflation, key: 'stagflation' },
    { label: t('signals.riskOff'),    value: probRiskOff,    key: 'risk_off' },
    { label: t('signals.deflation'),  value: probDeflation,  key: 'deflation' },
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
