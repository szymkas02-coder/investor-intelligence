// Stacked horizontal bar showing regime probabilities
const COLORS = {
  risk_on:     '#22c55e',
  stagflation: '#f97316',
  risk_off:    '#ef4444',
  deflation:   '#a855f7',
}

export default function RegimeBar({ probRiskOn, probRiskOff, probStagflation, probDeflation }) {
  const segments = [
    { label: 'Risk On',     value: probRiskOn,     key: 'risk_on' },
    { label: 'Stagflation', value: probStagflation, key: 'stagflation' },
    { label: 'Risk Off',    value: probRiskOff,     key: 'risk_off' },
    { label: 'Deflation',   value: probDeflation,   key: 'deflation' },
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
