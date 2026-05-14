import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import client from '../api/client'

function fetchDecision(lang) {
  return client.get(`/decision?lang=${lang}`).then(r => r.data)
}

function fetchProjection(years, monthly) {
  return client.get(`/decision/projection?years=${years}&monthly_pln=${monthly}`).then(r => r.data)
}

const ACTION_COLOR = { INVEST: '#22c55e', DCA: '#f97316', WAIT: '#ef4444' }
const ACTION_ICON  = { INVEST: '✓', DCA: '~', WAIT: '✗' }

export default function Decision() {
  const { t, i18n } = useTranslation()
  const lang = i18n.language === 'pl' ? 'pl' : 'en'
  const [years,   setYears]   = useState(20)
  const [monthly, setMonthly] = useState(500)

  const { data: dec, isLoading: decLoading, error: decError } = useQuery({
    queryKey: ['decision', lang],
    queryFn:  () => fetchDecision(lang),
    retry: 1,
  })

  const { data: proj, isLoading: projLoading } = useQuery({
    queryKey: ['projection', years, monthly],
    queryFn:  () => fetchProjection(years, monthly),
  })

  return (
    <div className="decision-page">
      <div className="card">
        <h2>{t('decision.title')}</h2>
        {decLoading ? <p>{t('decision.loading')}</p> : decError ? (
          <div className="error-box">
            <strong>{t('decision.loadFailed')}</strong>
            <p>{decError.response?.data?.detail ?? decError.message}</p>
            <p className="error-hint">{t('decision.mlHint')}</p>
          </div>
        ) : dec && (
          <>
            <div className="action-badge" style={{ background: ACTION_COLOR[dec.action] }}>
              {ACTION_ICON[dec.action]} {dec.action}
            </div>
            <span className="confidence-tag">{t('decision.confidence')}: {dec.confidence}</span>

            <ul className="reasons">
              {dec.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>

            {dec.flags.length > 0 && (
              <div className="flags">
                <strong>{t('decision.flags')}:</strong>
                {dec.flags.map((f, i) => <p key={i} className="flag">{f}</p>)}
              </div>
            )}

            <div className="signal-grid">
              <div><span>{t('decision.riskOffProb')}</span><strong>{(dec.signals.prob_risk_off * 100).toFixed(0)}%</strong></div>
              <div><span>{t('decision.stagflationProb')}</span><strong>{(dec.signals.prob_stagflation * 100).toFixed(0)}%</strong></div>
              <div><span>{t('decision.vol21d')}</span><strong>{dec.signals.vol_21d_forecast != null ? (dec.signals.vol_21d_forecast * 100).toFixed(1) + '%' : '—'}</strong></div>
              <div><span>{t('decision.usdplnNow')}</span><strong>{dec.signals.usdpln_current?.toFixed(4) ?? '—'}</strong></div>
              <div><span>{t('decision.usdpln90th')}</span><strong>{dec.signals.usdpln_upper_21d?.toFixed(4) ?? '—'}</strong></div>
              <div><span>{t('decision.usCpiYoy')}</span><strong>{dec.signals.cpi_us_yoy?.toFixed(1) ?? '—'}%</strong></div>
            </div>
          </>
        )}
      </div>

      <div className="card">
        <h2>{t('decision.projection')}</h2>
        <div className="proj-controls">
          <label>
            {t('decision.horizon')}
            <input type="number" min="1" max="50" value={years}
                   onChange={e => setYears(Number(e.target.value))} />
          </label>
          <label>
            {t('decision.monthly')}
            <input type="number" min="0" max="50000" step="50" value={monthly}
                   onChange={e => setMonthly(Number(e.target.value))} />
          </label>
        </div>

        {projLoading ? <p>{t('decision.loadingProj')}</p> : proj && (
          <>
            <div className="ensemble-grid">
              <div className="ensemble-item">
                <span>{t('decision.capeSignal')}</span>
                <strong>{(proj.ensemble.cape_return * 100).toFixed(1)}%</strong>
                <small>{t('decision.capeDecile', { decile: proj.ensemble.cape_decile, weight: (proj.ensemble.weights.cape * 100).toFixed(0) })}</small>
              </div>
              <div className="ensemble-item">
                <span>{t('decision.baseRate')}</span>
                <strong>{(proj.ensemble.base_rate_return * 100).toFixed(1)}%</strong>
                <small>{t('decision.baseRateNote', { weight: (proj.ensemble.weights.base_rate * 100).toFixed(0) })}</small>
              </div>
              <div className="ensemble-item">
                <span>{t('decision.momentum')}</span>
                <strong>{(proj.ensemble.momentum_return * 100).toFixed(1)}%</strong>
                <small>{t('decision.momentumNote', { adj: (proj.ensemble.momentum_adj >= 0 ? '+' : '') + (proj.ensemble.momentum_adj * 100).toFixed(2), weight: (proj.ensemble.weights.momentum * 100).toFixed(0) })}</small>
              </div>
              <div className="ensemble-item ensemble-result">
                <span>{t('decision.ensembleMedian')}</span>
                <strong>{(proj.ensemble.ensemble_median * 100).toFixed(1)}%</strong>
                <small>± {(proj.ensemble.ensemble_std * 100).toFixed(1)}% std · {t('decision.currentPortfolio', { value: proj.current_value_pln.toLocaleString('pl-PL', { maximumFractionDigits: 0 }) })}</small>
              </div>
            </div>

            <ResponsiveContainer width="100%" height={320}>
              <AreaChart data={proj.paths} margin={{ top: 10, right: 20, left: 20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="year" label={{ value: t('decision.year'), position: 'insideBottom', offset: -4 }} />
                <YAxis tickFormatter={v => `${(v / 1000).toFixed(0)}k`}
                       label={{ value: t('decision.pln'), angle: -90, position: 'insideLeft' }} />
                <Tooltip formatter={(v) => `${v.toLocaleString('pl-PL', { maximumFractionDigits: 0 })} PLN`} />
                <Legend />
                <Area type="monotone" dataKey="p90_pln" name={t('decision.p90label')}
                      stroke="#93c5fd" fill="#dbeafe" strokeWidth={1} />
                <Area type="monotone" dataKey="median_pln" name={t('decision.medianLabel')}
                      stroke="#3b82f6" fill="#bfdbfe" strokeWidth={2} />
                <Area type="monotone" dataKey="p10_pln" name={t('decision.p10label')}
                      stroke="#1d4ed8" fill="#93c5fd" strokeWidth={1} />
              </AreaChart>
            </ResponsiveContainer>

            <p className="proj-disclaimer">{t('decision.disclaimer')}</p>
          </>
        )}
      </div>
    </div>
  )
}
