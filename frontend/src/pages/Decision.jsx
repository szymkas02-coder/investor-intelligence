import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import client from '../api/client'

function fetchDecision() {
  return client.get('/decision').then(r => r.data)
}

function fetchProjection(years, monthly) {
  return client.get(`/decision/projection?years=${years}&monthly_pln=${monthly}`).then(r => r.data)
}

const ACTION_COLOR = { INVEST: '#22c55e', DCA: '#f97316', WAIT: '#ef4444' }
const ACTION_ICON  = { INVEST: '✓', DCA: '~', WAIT: '✗' }

export default function Decision() {
  const [years,   setYears]   = useState(20)
  const [monthly, setMonthly] = useState(500)

  const { data: dec, isLoading: decLoading, error: decError } = useQuery({
    queryKey: ['decision'],
    queryFn:  fetchDecision,
    retry: 1,
  })

  const { data: proj, isLoading: projLoading, refetch: refetchProj } = useQuery({
    queryKey: ['projection', years, monthly],
    queryFn:  () => fetchProjection(years, monthly),
  })

  return (
    <div className="decision-page">
      {/* Recommendation card */}
      <div className="card">
        <h2>Monthly Recommendation</h2>
        {decLoading ? <p>Loading...</p> : decError ? (
          <div className="error-box">
            <strong>Failed to load recommendation</strong>
            <p>{decError.response?.data?.detail ?? decError.message}</p>
            <p className="error-hint">Make sure the backend is running and ML models are trained (<code>python ml/regime.py train</code>).</p>
          </div>
        ) : dec && (
          <>
            <div className="action-badge"
                 style={{ background: ACTION_COLOR[dec.action] }}>
              {ACTION_ICON[dec.action]} {dec.action}
            </div>
            <span className="confidence-tag">Confidence: {dec.confidence}</span>

            <ul className="reasons">
              {dec.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>

            {dec.flags.length > 0 && (
              <div className="flags">
                <strong>Flags:</strong>
                {dec.flags.map((f, i) => <p key={i} className="flag">{f}</p>)}
              </div>
            )}

            <div className="signal-grid">
              <div><span>Risk-off prob</span><strong>{(dec.signals.prob_risk_off * 100).toFixed(0)}%</strong></div>
              <div><span>Stagflation prob</span><strong>{(dec.signals.prob_stagflation * 100).toFixed(0)}%</strong></div>
              <div><span>Vol 21d (ann.)</span><strong>{dec.signals.vol_21d_forecast != null ? (dec.signals.vol_21d_forecast * 100).toFixed(1) + '%' : '—'}</strong></div>
              <div><span>USD/PLN now</span><strong>{dec.signals.usdpln_current?.toFixed(4) ?? '—'}</strong></div>
              <div><span>USD/PLN 90th 21d</span><strong>{dec.signals.usdpln_upper_21d?.toFixed(4) ?? '—'}</strong></div>
              <div><span>US CPI YoY</span><strong>{dec.signals.cpi_us_yoy?.toFixed(1) ?? '—'}%</strong></div>
            </div>
          </>
        )}
      </div>

      {/* Projection */}
      <div className="card">
        <h2>Long-term Portfolio Projection</h2>
        <div className="proj-controls">
          <label>
            Horizon (years)
            <input type="number" min="1" max="50" value={years}
                   onChange={e => setYears(Number(e.target.value))} />
          </label>
          <label>
            Monthly contribution (PLN)
            <input type="number" min="0" max="50000" step="50" value={monthly}
                   onChange={e => setMonthly(Number(e.target.value))} />
          </label>
        </div>

        {projLoading ? <p>Loading projection...</p> : proj && (
          <>
            {/* Ensemble breakdown */}
            <div className="ensemble-grid">
              <div className="ensemble-item">
                <span>US CAPE signal</span>
                <strong>{(proj.ensemble.cape_return * 100).toFixed(1)}%</strong>
                <small>decile {proj.ensemble.cape_decile}/10 · weight {(proj.ensemble.weights.cape * 100).toFixed(0)}%</small>
              </div>
              <div className="ensemble-item">
                <span>Historical base rate</span>
                <strong>{(proj.ensemble.base_rate_return * 100).toFixed(1)}%</strong>
                <small>DMS 2025 global · weight {(proj.ensemble.weights.base_rate * 100).toFixed(0)}%</small>
              </div>
              <div className="ensemble-item">
                <span>Momentum / valuation</span>
                <strong>{(proj.ensemble.momentum_return * 100).toFixed(1)}%</strong>
                <small>adj {proj.ensemble.momentum_adj >= 0 ? '+' : ''}{(proj.ensemble.momentum_adj * 100).toFixed(2)}% · weight {(proj.ensemble.weights.momentum * 100).toFixed(0)}%</small>
              </div>
              <div className="ensemble-item ensemble-result">
                <span>Ensemble median real return</span>
                <strong>{(proj.ensemble.ensemble_median * 100).toFixed(1)}%</strong>
                <small>± {(proj.ensemble.ensemble_std * 100).toFixed(1)}% std · current portfolio {proj.current_value_pln.toLocaleString('pl-PL', { maximumFractionDigits: 0 })} PLN</small>
              </div>
            </div>

            <ResponsiveContainer width="100%" height={320}>
              <AreaChart data={proj.paths}
                         margin={{ top: 10, right: 20, left: 20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="year" label={{ value: 'Year', position: 'insideBottom', offset: -4 }} />
                <YAxis tickFormatter={v => `${(v / 1000).toFixed(0)}k`}
                       label={{ value: 'PLN', angle: -90, position: 'insideLeft' }} />
                <Tooltip formatter={(v) => `${v.toLocaleString('pl-PL', { maximumFractionDigits: 0 })} PLN`} />
                <Legend />
                <Area type="monotone" dataKey="p90_pln" name="90th pct"
                      stroke="#93c5fd" fill="#dbeafe" strokeWidth={1} />
                <Area type="monotone" dataKey="median_pln" name="Median"
                      stroke="#3b82f6" fill="#bfdbfe" strokeWidth={2} />
                <Area type="monotone" dataKey="p10_pln" name="10th pct"
                      stroke="#1d4ed8" fill="#93c5fd" strokeWidth={1} />
              </AreaChart>
            </ResponsiveContainer>

            <p className="proj-disclaimer">
              Ensemble of three signals: US CAPE (Asness/AQR 2012), long-run historical base rate
              (Dimson-Marsh-Staunton Global Returns Yearbook 2025, 1900–2024), and momentum/valuation
              adjustment from live market data. Real returns — inflation not included. Not financial advice.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
