import { useTranslation } from 'react-i18next'

function volColor(v) {
  if (v > 0.30) return '#ef4444'
  if (v > 0.20) return '#f97316'
  return '#22c55e'
}

export default function VolGauge({ label, forecast, lower, upper }) {
  const { t } = useTranslation()
  const color = volColor(forecast)
  return (
    <div className="vol-gauge">
      <div className="vol-label">{label}</div>
      <div className="vol-value" style={{ color }}>
        {(forecast * 100).toFixed(1)}%
      </div>
      <div className="vol-band">
        [{(lower * 100).toFixed(1)}% – {(upper * 100).toFixed(1)}%]
      </div>
      <div className="vol-desc">{t('components.annualised')}</div>
    </div>
  )
}
