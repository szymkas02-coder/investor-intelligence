/**
 * Invest.jsx — the "keep investing" page (formerly /decision).
 *
 * Three sections:
 *   1. Verdict — calm "invest your monthly contribution" message + IKE remaining
 *      + optional PLN/USD warning when the 21d 90th-percentile is >5% above current.
 *   2. Long-run S&P chart — Shiller real-total-return index 1871–today, log y-axis,
 *      one line, mostly visual: "this is what staying invested looks like."
 *   3. Historical investment widget — user picks date + amount + lump-sum-vs-DCA,
 *      backend simulates against Shiller, returns equity curve + summary stats.
 *   4. Long-term projection — horizon-weighted CAPE/momentum/base-rate ensemble
 *      (preserved unchanged from the old /decision page).
 */
import { useState, useRef, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  AreaChart, LineChart, ComposedChart, Area, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import client from '../api/client'

const fetchStatus     = (lang)  => client.get(`/invest/status?lang=${lang}`).then(r => r.data)
const fetchLongrun    = ()      => client.get('/invest/longrun?sample_months=3').then(r => r.data)
const fetchProjection = (y, m)  => client.get(`/invest/projection?years=${y}&monthly_pln=${m}`).then(r => r.data)
const fetchSimulation = (params) => client.get('/invest/historical-simulation', { params }).then(r => r.data)

function fmtPLN(v, digits = 0) {
  if (v == null) return '—'
  return v.toLocaleString('pl-PL', { maximumFractionDigits: digits }) + ' PLN'
}

function Card({ children, style }) {
  return (
    <div className="card" style={style}>{children}</div>
  )
}

// ─── 1. Verdict ────────────────────────────────────────────────────────────
function Verdict({ status, t, pl }) {
  if (!status) return null
  const pct = status.ike_limit ? Math.min(100, ((status.ike_contributed ?? 0) / status.ike_limit) * 100) : null
  return (
    <Card>
      <div style={{ borderLeft: '4px solid #22c55e', paddingLeft: '1rem', marginBottom: '1.25rem' }}>
        <div style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.4rem' }}>
          {t('invest.verdictLabel', { defaultValue: pl ? 'W tym miesiącu' : 'This month' })}
        </div>
        <p style={{ fontSize: '1.05rem', lineHeight: 1.55, color: '#0f172a', margin: 0 }}>
          {status.headline}
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
        {status.ike_limit != null && (
          <div>
            <div style={{ fontSize: '0.78rem', color: '#94a3b8', marginBottom: '0.3rem' }}>
              {t('invest.ikeRemainingLabel', { defaultValue: pl ? 'Limit IKE 2026' : 'IKE 2026 limit' })}
            </div>
            <div style={{ fontSize: '1rem', color: '#0f172a', marginBottom: '0.5rem' }}>
              <strong>{fmtPLN(status.ike_contributed)}</strong>
              <span style={{ color: '#64748b' }}> / {fmtPLN(status.ike_limit)}</span>
            </div>
            <div style={{ height: 6, background: '#f1f5f9', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${pct?.toFixed(0)}%`, background: '#3b82f6' }} />
            </div>
            <div style={{ fontSize: '0.78rem', color: '#3b82f6', marginTop: '0.3rem' }}>
              {fmtPLN(status.ike_remaining)} {pl ? 'pozostało' : 'remaining'}
            </div>
          </div>
        )}
        {status.fx_flag && (
          <div style={{ background: '#fef3c7', borderLeft: '3px solid #f59e0b', padding: '0.6rem 0.8rem', borderRadius: 4, fontSize: '0.82rem', color: '#78350f', lineHeight: 1.5 }}>
            <strong>{pl ? 'Uwaga walutowa: ' : 'FX note: '}</strong>{status.fx_flag}
          </div>
        )}
      </div>
    </Card>
  )
}

// ─── 2. Long-run S&P chart ─────────────────────────────────────────────────
function LongRunChart({ data, t, pl }) {
  if (!data?.data) return <p>{t('common.loading', { defaultValue: 'Loading…' })}</p>
  // Log scale: Recharts needs scale='log' + a positive domain.
  return (
    <Card>
      <h2 style={{ marginTop: 0 }}>
        {pl ? 'Akcje na długim horyzoncie — 155 lat (S&P 500, realny zwrot całkowity)' : 'Equities on a long horizon — 155 years (S&P 500, real total return)'}
      </h2>
      <p style={{ color: '#64748b', fontSize: '0.88rem', marginTop: 0, marginBottom: '1rem' }}>
        {pl
          ? 'Indeks zaczyna od 100 w styczniu 1871. Skala logarytmiczna — każda linia siatki to ×10. Reinwestowane dywidendy, skorygowane o inflację. Wszystkie kryzysy historyczne (1929, 1973, 2000, 2008, 2020) są tutaj widoczne — i przebite.'
          : 'Index starts at 100 in January 1871. Log y-axis — each gridline is ×10. Dividends reinvested, CPI-adjusted. Every historical crash (1929, 1973, 2000, 2008, 2020) is on this chart — and overtaken.'}
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data.data} margin={{ top: 5, right: 16, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="date" tickFormatter={d => d?.slice(0, 4)} minTickGap={50} tick={{ fontSize: 10 }} />
          <YAxis scale="log" domain={['auto', 'auto']} tickFormatter={v => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(0)} tick={{ fontSize: 10 }} />
          <Tooltip formatter={v => v.toLocaleString('en', { maximumFractionDigits: 0 })} labelFormatter={d => d} />
          <Line type="monotone" dataKey="rtr" stroke="#1e40af" strokeWidth={1.5} dot={false} name={pl ? 'Indeks realnego zwrotu' : 'Real total return index'} />
        </LineChart>
      </ResponsiveContainer>
      <p style={{ fontSize: '0.78rem', color: '#94a3b8', marginTop: '0.6rem', textAlign: 'right' }}>
        {pl ? 'Dane: Robert Shiller, Yale (irrationalexuberance.com).' : 'Data: Robert Shiller, Yale (irrationalexuberance.com).'}
      </p>
    </Card>
  )
}

// ─── 3. Historical simulation widget ───────────────────────────────────────
function HistoricalWidget({ t, pl, longrun }) {
  const minDate = longrun?.start_date ?? '1871-01-01'
  const maxDate = longrun?.end_date   ?? '2026-04-01'

  const [startDate,  setStartDate]  = useState('1990-01-01')
  const [endDate,    setEndDate]    = useState(maxDate)
  const [amount,     setAmount]     = useState(10000)
  const [mode,       setMode]       = useState('lump_sum')
  const [dcaMonths,  setDcaMonths]  = useState(12)

  // Debounce so dragging the date inputs doesn't fire a request per keystroke
  const [submitted, setSubmitted] = useState({ start_date: startDate, end_date: endDate, amount_pln: amount, mode, dca_months: dcaMonths })

  const { data: sim, isLoading, error } = useQuery({
    queryKey: ['invest-sim', submitted],
    queryFn:  () => fetchSimulation(submitted),
    enabled:  !!submitted.start_date && !!submitted.end_date && submitted.amount_pln > 0,
    retry:    false,
  })

  function submit() {
    setSubmitted({
      start_date: startDate,
      end_date:   endDate,
      amount_pln: Math.max(1, Number(amount) || 0),
      mode,
      dca_months: Math.max(1, Math.min(240, Number(dcaMonths) || 12)),
    })
  }

  return (
    <Card>
      <h2 style={{ marginTop: 0 }}>
        {pl ? 'Co by się stało, gdybym…' : 'What if I had…'}
      </h2>
      <p style={{ color: '#64748b', fontSize: '0.88rem', marginTop: 0, marginBottom: '1rem' }}>
        {pl
          ? 'Wpisz datę, kwotę i wybierz strategię — symulacja przejdzie przez kolejne 100+ lat danych Shillera (realne zwroty z dywidendami).'
          : 'Pick a date, amount, and strategy — the simulation runs against 100+ years of Shiller data (real total returns with dividends reinvested).'}
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '0.75rem', marginBottom: '1rem', alignItems: 'end' }}>
        <label style={{ display: 'flex', flexDirection: 'column', fontSize: '0.78rem', color: '#475569' }}>
          {pl ? 'Data startu' : 'Start date'}
          <input type="date" value={startDate} min={minDate} max={maxDate}
                 onChange={e => setStartDate(e.target.value)}
                 style={{ marginTop: 4, padding: '0.45rem 0.6rem', border: '1px solid #cbd5e1', borderRadius: 4, fontSize: '0.88rem' }} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', fontSize: '0.78rem', color: '#475569' }}>
          {pl ? 'Data końca' : 'End date'}
          <input type="date" value={endDate} min={minDate} max={maxDate}
                 onChange={e => setEndDate(e.target.value)}
                 style={{ marginTop: 4, padding: '0.45rem 0.6rem', border: '1px solid #cbd5e1', borderRadius: 4, fontSize: '0.88rem' }} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', fontSize: '0.78rem', color: '#475569' }}>
          {pl ? 'Kwota (PLN)' : 'Amount (PLN)'}
          <input type="number" value={amount} min="1" max="10000000" step="100"
                 onChange={e => setAmount(e.target.value)}
                 style={{ marginTop: 4, padding: '0.45rem 0.6rem', border: '1px solid #cbd5e1', borderRadius: 4, fontSize: '0.88rem' }} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', fontSize: '0.78rem', color: '#475569' }}>
          {pl ? 'Strategia' : 'Strategy'}
          <select value={mode} onChange={e => setMode(e.target.value)}
                  style={{ marginTop: 4, padding: '0.45rem 0.6rem', border: '1px solid #cbd5e1', borderRadius: 4, fontSize: '0.88rem' }}>
            <option value="lump_sum">{pl ? 'Lump-sum (jednorazowo)' : 'Lump-sum (all at once)'}</option>
            <option value="dca">{pl ? 'DCA (uśrednianie)' : 'DCA (averaged)'}</option>
          </select>
        </label>
        {mode === 'dca' && (
          <label style={{ display: 'flex', flexDirection: 'column', fontSize: '0.78rem', color: '#475569' }}>
            {pl ? 'Liczba miesięcy DCA' : 'DCA months'}
            <input type="number" value={dcaMonths} min="1" max="240" step="1"
                   onChange={e => setDcaMonths(e.target.value)}
                   style={{ marginTop: 4, padding: '0.45rem 0.6rem', border: '1px solid #cbd5e1', borderRadius: 4, fontSize: '0.88rem' }} />
          </label>
        )}
        <button onClick={submit}
                style={{ padding: '0.55rem 1rem', background: '#3b82f6', color: '#fff', border: 'none', borderRadius: 4, fontWeight: 600, cursor: 'pointer', fontSize: '0.85rem', height: 'fit-content' }}>
          {pl ? 'Oblicz' : 'Calculate'}
        </button>
      </div>

      {isLoading && <p style={{ color: '#94a3b8', fontSize: '0.88rem' }}>{pl ? 'Liczę…' : 'Calculating…'}</p>}
      {error && (
        <p style={{ color: '#ef4444', fontSize: '0.85rem' }}>
          {error.response?.data?.detail ?? error.message}
        </p>
      )}

      {sim && !isLoading && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '0.75rem', marginBottom: '1rem' }}>
            <Stat label={pl ? 'Wpłacono łącznie' : 'Total invested'} value={fmtPLN(sim.total_invested)} />
            <Stat label={pl ? 'Wartość końcowa (realnie)' : 'Final value (real)'} value={fmtPLN(sim.final_value_real)} color="#22c55e" />
            <Stat label={pl ? 'Zwrot łącznie' : 'Total return'} value={`${sim.return_pct >= 0 ? '+' : ''}${sim.return_pct.toFixed(1)}%`} color={sim.return_pct >= 0 ? '#22c55e' : '#ef4444'} />
            <Stat label={pl ? 'CAGR (rocznie)' : 'CAGR (annualised)'} value={`${sim.cagr_pct.toFixed(2)}%`} color="#3b82f6" />
            <Stat label={pl ? 'Najgorszy spadek' : 'Worst drawdown'} value={`${sim.max_drawdown_pct.toFixed(1)}%`} color="#ef4444" />
            <Stat label={pl ? 'Trzymane (m-cy)' : 'Months held'} value={`${sim.months_held}`} />
          </div>

          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={sim.equity_curve} margin={{ top: 5, right: 16, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="date" tickFormatter={d => d?.slice(0, 4)} minTickGap={60} tick={{ fontSize: 10 }} />
              <YAxis tickFormatter={v => `${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 10 }} />
              <Tooltip formatter={(v) => v.toLocaleString('pl-PL', { maximumFractionDigits: 0 }) + ' PLN'} labelFormatter={d => d} />
              <Legend wrapperStyle={{ fontSize: '0.78rem' }} />
              <Area type="monotone" dataKey="value_real" fill="#bfdbfe" stroke="#3b82f6" strokeWidth={1.5} name={pl ? 'Wartość portfela (realna)' : 'Portfolio value (real)'} />
              <Line type="monotone" dataKey="invested" stroke="#64748b" strokeDasharray="4 2" strokeWidth={1.2} dot={false} name={pl ? 'Wpłacono' : 'Invested'} />
            </ComposedChart>
          </ResponsiveContainer>

          <p style={{ fontSize: '0.78rem', color: '#94a3b8', marginTop: '0.6rem' }}>
            {pl
              ? 'Wykres pokazuje wartość portfela w realnych PLN (skorygowanych o inflację z okresu startu). Szara przerywana = łączna kwota wpłacona.'
              : 'Chart shows portfolio value in real PLN (CPI-adjusted to the start date). Grey dashed = cumulative invested.'}
          </p>
        </>
      )}
    </Card>
  )
}

function Stat({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: '0.72rem', color: '#94a3b8', marginBottom: '0.2rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</div>
      <div style={{ fontSize: '1.05rem', fontWeight: 700, color: color ?? '#0f172a' }}>{value}</div>
    </div>
  )
}

// ─── 4. Projection (preserved from old Decision page, simplified) ──────────
function Projection({ t, pl }) {
  const [yearsInput,   setYearsInput]   = useState(20)
  const [monthlyInput, setMonthlyInput] = useState(500)
  const [years,   setYears]   = useState(20)
  const [monthly, setMonthly] = useState(500)
  const debounceRef = useRef(null)

  function handleYearsChange(val) {
    setYearsInput(val)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      const n = Math.max(1, Math.min(50, Number(val)))
      if (!isNaN(n) && n > 0) setYears(n)
    }, 600)
  }
  function handleMonthlyChange(val) {
    setMonthlyInput(val)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      const n = Math.max(0, Math.min(50000, Number(val)))
      if (!isNaN(n)) setMonthly(n)
    }, 600)
  }

  const { data: proj, isLoading } = useQuery({
    queryKey: ['invest-projection', years, monthly],
    queryFn:  () => fetchProjection(years, monthly),
  })

  return (
    <Card>
      <h2 style={{ marginTop: 0 }}>{t('decision.projection')}</h2>
      <div className="proj-controls">
        <label>
          {t('decision.horizon')}
          <input type="number" min="1" max="50" value={yearsInput}
                 onChange={e => handleYearsChange(e.target.value)} />
        </label>
        <label>
          {t('decision.monthly')}
          <input type="number" min="0" max="50000" step="50" value={monthlyInput}
                 onChange={e => handleMonthlyChange(e.target.value)} />
        </label>
      </div>

      {isLoading ? <p>{t('decision.loadingProj')}</p> : proj && (
        <>
          <div className="ensemble-grid">
            {proj.ensemble.weights.cape === 0 ? (
              <div className="ensemble-item" style={{ opacity: 0.4 }}>
                <span>{t('decision.capeSignal')}</span><strong>—</strong>
                <small>{t('decision.capeNA')}</small>
              </div>
            ) : (
              <div className="ensemble-item">
                <span>{t('decision.capeSignal')}</span>
                <strong>{(proj.ensemble.cape_return * 100).toFixed(1)}%</strong>
                <small>{t('decision.capeDecile', { decile: proj.ensemble.cape_decile, weight: (proj.ensemble.weights.cape * 100).toFixed(0) })}</small>
              </div>
            )}
            <div className="ensemble-item">
              <span>{t('decision.baseRate')}</span>
              <strong>{(proj.ensemble.base_rate_return * 100).toFixed(1)}%</strong>
              <small>{t('decision.baseRateNote', { weight: (proj.ensemble.weights.base_rate * 100).toFixed(0) })}</small>
            </div>
            {proj.ensemble.weights.momentum === 0 ? (
              <div className="ensemble-item" style={{ opacity: 0.4 }}>
                <span>{t('decision.momentum')}</span><strong>—</strong>
                <small>{t('decision.momentumNA')}</small>
              </div>
            ) : (
              <div className="ensemble-item">
                <span>{t('decision.momentum')}</span>
                <strong>{(proj.ensemble.momentum_return * 100).toFixed(1)}%</strong>
                <small>{t('decision.momentumNote', { adj: (proj.ensemble.momentum_adj >= 0 ? '+' : '') + (proj.ensemble.momentum_adj * 100).toFixed(2), weight: (proj.ensemble.weights.momentum * 100).toFixed(0) })}</small>
              </div>
            )}
            <div className="ensemble-item ensemble-result">
              <span>{t('decision.ensembleMedian')}</span>
              <strong>{(proj.ensemble.ensemble_median * 100).toFixed(1)}%</strong>
              <small>± {(proj.ensemble.ensemble_std * 100).toFixed(1)}% std · {t('decision.currentPortfolio', { value: proj.current_value_pln.toLocaleString('pl-PL', { maximumFractionDigits: 0 }) })}</small>
            </div>
          </div>

          <p className="proj-horizon-note">{t('decision.horizonNote')}</p>

          <ResponsiveContainer width="100%" height={320}>
            <AreaChart data={proj.paths} margin={{ top: 10, right: 20, left: 20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="year" label={{ value: t('decision.year'), position: 'insideBottom', offset: -4 }} />
              <YAxis tickFormatter={v => `${(v / 1000).toFixed(0)}k`}
                     label={{ value: t('decision.pln'), angle: -90, position: 'insideLeft' }} />
              <Tooltip formatter={(v) => `${v.toLocaleString('pl-PL', { maximumFractionDigits: 0 })} PLN`} />
              <Legend />
              <Area type="monotone" dataKey="p90_pln" name={t('decision.p90label')} stroke="#93c5fd" fill="#dbeafe" strokeWidth={1} />
              <Area type="monotone" dataKey="median_pln" name={t('decision.medianLabel')} stroke="#3b82f6" fill="#bfdbfe" strokeWidth={2} />
              <Area type="monotone" dataKey="p10_pln" name={t('decision.p10label')} stroke="#1d4ed8" fill="#93c5fd" strokeWidth={1} />
            </AreaChart>
          </ResponsiveContainer>

          <p className="proj-disclaimer">{t('decision.disclaimer')}</p>
          <p className="proj-disclaimer" style={{ marginTop: '0.5rem', borderTop: '1px solid #e2e8f0', paddingTop: '0.5rem' }}>
            {t('decision.disclaimerEarnings')}
          </p>
        </>
      )}
    </Card>
  )
}

// ─── Page composer ─────────────────────────────────────────────────────────
export default function Invest() {
  const { t, i18n } = useTranslation()
  const pl  = i18n.language === 'pl'
  const lang = pl ? 'pl' : 'en'

  const { data: status }  = useQuery({ queryKey: ['invest-status', lang], queryFn: () => fetchStatus(lang) })
  const { data: longrun } = useQuery({ queryKey: ['invest-longrun'],     queryFn: fetchLongrun })

  return (
    <div className="decision-page">
      <Verdict       status={status} t={t} pl={pl} />
      <LongRunChart  data={longrun}  t={t} pl={pl} />
      <HistoricalWidget t={t} pl={pl} longrun={longrun} />
      <Projection    t={t} pl={pl} />
    </div>
  )
}
