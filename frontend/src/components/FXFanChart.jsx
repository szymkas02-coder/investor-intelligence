import { useTranslation } from 'react-i18next'

export default function FXFanChart({ signals, current }) {
  const { t } = useTranslation()

  if (!signals?.length) return <p>{t('components.noFxForecast')}</p>

  return (
    <div>
      <p style={{ fontSize: '0.8rem', color: '#6b7280', marginBottom: '0.75rem' }}>
        {t('components.fxForecastDesc')} <strong>{current?.toFixed(4)}</strong>
      </p>
      <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
        {signals.map(s => {
          const upside   = ((s.rate_upper - current) / current * 100).toFixed(1)
          const downside = ((s.rate_lower - current) / current * 100).toFixed(1)
          const bearish  = s.rate_upper > current * 1.02
          return (
            <div key={s.horizon_days} className="fx-block"
                 style={{ borderLeft: `3px solid ${bearish ? '#f97316' : '#22c55e'}`, paddingLeft: '0.75rem' }}>
              <div className="fx-horizon">{t('components.fxForecastHorizon', { days: s.horizon_days })}</div>
              <div className="fx-point">{s.rate_point.toFixed(4)} PLN</div>
              <div className="fx-band">
                <span title={t('components.fxP10')}>
                  {downside > 0 ? '+' : ''}{downside}%
                </span>
                {' / '}
                <span title={t('components.fxP90')} style={{ color: bearish ? '#f97316' : 'inherit' }}>
                  +{upside}%
                </span>
              </div>
              <div className="fx-label">{t('components.fxDownsideUpside')}</div>
              <div className="fx-band" style={{ marginTop: '0.2rem', fontSize: '0.7rem', color: '#94a3b8' }}>
                {s.rate_lower.toFixed(4)} – {s.rate_upper.toFixed(4)}
              </div>
            </div>
          )
        })}
      </div>
      <p style={{ fontSize: '0.72rem', color: '#94a3b8', marginTop: '0.75rem', fontStyle: 'italic' }}>
        {t('components.fxMeeseRogoff')}
      </p>
    </div>
  )
}
