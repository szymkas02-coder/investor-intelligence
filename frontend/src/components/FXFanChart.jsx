import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer, Cell,
} from 'recharts'

export default function FXFanChart({ signals, current }) {
  if (!signals?.length) return <p>No FX forecast available.</p>

  const data = signals.map(s => ({
    name:   `${s.horizon_days}d`,
    lower:  parseFloat(s.rate_lower.toFixed(4)),
    point:  parseFloat(s.rate_point.toFixed(4)),
    upper:  parseFloat(s.rate_upper.toFixed(4)),
    range:  parseFloat((s.rate_upper - s.rate_lower).toFixed(4)),
  }))

  return (
    <div>
      <p style={{ fontSize: '0.8rem', color: '#6b7280', marginBottom: '0.75rem' }}>
        Median forecast with 10th–90th percentile uncertainty band. Current: <strong>{current?.toFixed(4)}</strong>
      </p>
      <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
        {signals.map(s => {
          const upside = ((s.rate_upper - current) / current * 100).toFixed(1)
          const downside = ((s.rate_lower - current) / current * 100).toFixed(1)
          const bearish = s.rate_upper > current * 1.02
          return (
            <div key={s.horizon_days} className="fx-block"
                 style={{ borderLeft: `3px solid ${bearish ? '#f97316' : '#22c55e'}`, paddingLeft: '0.75rem' }}>
              <div className="fx-horizon">{s.horizon_days}d forecast</div>
              <div className="fx-point">{s.rate_point.toFixed(4)} PLN</div>
              <div className="fx-band">
                <span title="10th pct (PLN strengthens)">
                  {downside > 0 ? '+' : ''}{downside}%
                </span>
                {' / '}
                <span title="90th pct (PLN weakens)" style={{ color: bearish ? '#f97316' : 'inherit' }}>
                  +{upside}%
                </span>
              </div>
              <div className="fx-label">downside / upside vs today</div>
              <div className="fx-band" style={{ marginTop: '0.2rem', fontSize: '0.7rem', color: '#94a3b8' }}>
                {s.rate_lower.toFixed(4)} – {s.rate_upper.toFixed(4)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
