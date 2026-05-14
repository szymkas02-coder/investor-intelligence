import { useState, useRef, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  ComposedChart, AreaChart, LineChart,
  Area, Line,
  XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import client from '../api/client'

const REGIME_COLOR = {
  risk_on:     '#22c55e',
  risk_off:    '#ef4444',
  stagflation: '#f97316',
  deflation:   '#a855f7',
}
const REGIME_LABEL = {
  risk_on: 'Risk-on', risk_off: 'Risk-off',
  stagflation: 'Stagflation', deflation: 'Deflation',
}

const tickerLabel = (t, tickerList) => {
  const found = tickerList?.find(x => x.ticker === t)
  return found?.name && found.name !== t ? `${found.name} (${t})` : t
}

// All available, use 9999 as sentinel for "all data"
const DAY_OPTIONS = [
  { label: '6M',  days: 180  },
  { label: '1Y',  days: 365  },
  { label: '3Y',  days: 1095 },
  { label: '5Y',  days: 1825 },
  { label: '10Y', days: 3650 },
  { label: 'All', days: 9999 },
]

const fetch = (url) => client.get(url).then(r => r.data)
const fetchTickers = ()              => fetch('/tickers')
const fetchPrices = (ticker, days) => fetch(`/history/prices?ticker=${ticker}&days=${days}`)
const fetchRegime = (days)          => fetch(`/history/regime?days=${days}`)
const fetchMacro  = (series, days)  => fetch(`/history/macro?series=${series}&days=${days}`)
const fetchFX     = (days)          => fetch(`/history/fx?days=${days}`)
const fetchCAPE   = (days)          => fetch(`/history/cape?days=${days}`)

// X-axis tick formatter: show year if period > 1Y, else "Jan 25"
function makeTickFmt(days) {
  if (days > 365) {
    return (d) => {
      if (!d) return ''
      const dt = new Date(d)
      // Always show year label — but only for the ticks we've selected
      return String(dt.getFullYear())
    }
  }
  return (d) => {
    if (!d) return ''
    const dt = new Date(d)
    return dt.toLocaleString('en', { month: 'short' }) + ' ' + String(dt.getFullYear()).slice(2)
  }
}

// Pick evenly spaced ticks; for >1Y only pick one per year to avoid crowding
function pickTicks(rows, days, n = 10) {
  if (!rows?.length) return []
  if (days > 365) {
    // One tick per year (first trading day of each year in the dataset)
    const seen = new Set()
    return rows.filter(r => {
      const yr = r.date?.slice(0, 4)
      if (!yr || seen.has(yr)) return false
      seen.add(yr); return true
    }).map(r => r.date)
  }
  const step = Math.max(1, Math.floor(rows.length / n))
  return rows.filter((_, i) => i % step === 0 || i === rows.length - 1).map(r => r.date)
}

function mergeOverlay(priceRows, regimeRows) {
  const map = {}
  for (const r of regimeRows) map[r.date] = r.regime
  // Convert price_pln to cumulative return (%) from first data point
  // e.g. if first price is 100 and today is 150, return = +50%
  const base = priceRows[0]?.price_pln
  return priceRows.map(p => ({
    ...p,
    regime:         map[p.date] ?? null,
    cum_return_pct: base && p.price_pln != null
                      ? +((p.price_pln / base - 1) * 100).toFixed(2)
                      : null,
  }))
}

function RegimeDot({ cx, cy, payload }) {
  if (!payload?.regime) return null
  return <circle cx={cx} cy={cy} r={3} fill={REGIME_COLOR[payload.regime] ?? '#6b7280'} fillOpacity={0.8} />
}

function SectionHeader({ title, subtitle }) {
  return (
    <div className="hist-section-header">
      <h3>{title}</h3>
      {subtitle && <span className="hist-subtitle">{subtitle}</span>}
    </div>
  )
}

function Placeholder({ loading, error }) {
  const msg = error ? 'Failed to load — try refreshing' : loading ? 'Loading...' : 'No data available'
  const color = error ? '#ef4444' : '#94a3b8'
  return (
    <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color, fontSize: '0.85rem' }}>
      {msg}
    </div>
  )
}

function makeXAxis(rows, days) {
  return {
    dataKey:      'date',
    ticks:        pickTicks(rows, days),
    tickFormatter: makeTickFmt(days),
    tick:         { fontSize: 11 },
    angle:        -30,
    textAnchor:   'end',
    height:       44,
  }
}

export default function History() {
  const { t } = useTranslation()
  const [ticker,       setTicker]       = useState('VWCE.DE')
  const [days,         setDays]         = useState(1095)
  const [tickerSearch, setTickerSearch] = useState('')
  const [tickerOpen,   setTickerOpen]   = useState(false)
  const tickerRef = useRef(null)

  useEffect(() => {
    function handleClick(e) {
      if (tickerRef.current && !tickerRef.current.contains(e.target)) setTickerOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])
  const queryClient = useQueryClient()

  // Dynamic ticker list from the database — updates automatically when new ETFs are added
  const { data: tickersData } = useQuery({
    queryKey: ['tickers'],
    queryFn: fetchTickers,
    staleTime: 10 * 60 * 1000,
  })
  const availableTickers = tickersData ?? []
  const refetchAll = () => queryClient.invalidateQueries({ queryKey: ['hp'] })
    || queryClient.invalidateQueries({ queryKey: ['hr'] })
    || queryClient.invalidateQueries({ queryKey: ['hrat'] })
    || queryClient.invalidateQueries({ queryKey: ['hcpi'] })
    || queryClient.invalidateQueries({ queryKey: ['hrisk'] })
    || queryClient.invalidateQueries({ queryKey: ['hfx'] })
    || queryClient.invalidateQueries({ queryKey: ['hcape'] })
    || queryClient.invalidateQueries({ queryKey: ['hlab'] })
    || queryClient.invalidateQueries({ queryKey: ['hgold'] })

  // All queries fire independently — DuckDB shared connection serialises them safely.
  // retry:false — show error immediately, never hang as infinite spinner.
  const q = { staleTime: 5 * 60 * 1000, retry: false }

  const { data: priceData,  isLoading: pl,   isError: pe  } = useQuery({ queryKey: ['hp', ticker, days], queryFn: () => fetchPrices(ticker, days), ...q })
  const { data: regimeData, isLoading: rl,   isError: re  } = useQuery({ queryKey: ['hr', days],         queryFn: () => fetchRegime(days), ...q })
  const { data: rateData,   isLoading: ral,  isError: rae } = useQuery({ queryKey: ['hrat', days],       queryFn: () => fetchMacro('fed_funds_rate,ecb_rate,nbp_rate', days), ...q })
  const { data: cpiData,    isLoading: cl,   isError: ce  } = useQuery({ queryKey: ['hcpi', days],       queryFn: () => fetchMacro('cpi_us_yoy,cpi_ea_yoy,cpi_pl_yoy', days), ...q })
  const { data: riskData,   isLoading: rsl,  isError: rse } = useQuery({ queryKey: ['hrisk', days],      queryFn: () => fetchMacro('vix_close,spread_10y_3m,hy_spread', days), ...q })
  const { data: fxData,     isLoading: fxl,  isError: fxe } = useQuery({ queryKey: ['hfx', days],        queryFn: () => fetchFX(days), ...q })
  const { data: capeData,   isLoading: capl, isError: cape} = useQuery({ queryKey: ['hcape', days],       queryFn: () => fetchCAPE(days), ...q })
  const { data: laborData,  isLoading: ll,   isError: le  } = useQuery({ queryKey: ['hlab', days],        queryFn: () => fetchMacro('unemployment_us', days), ...q })
  const { data: goldData,   isLoading: gl,   isError: ge  } = useQuery({ queryKey: ['hgold', days],       queryFn: () => fetchMacro('gold_ret_21d', days), ...q })

  const anyError = pe || re || rae || ce || rse || fxe || cape || le || ge

  const priceRows  = priceData?.rows   ?? []
  const regimeRows = regimeData?.rows  ?? []
  const rateRows   = rateData?.rows    ?? []
  const cpiRows    = cpiData?.rows     ?? []
  const fxRows     = fxData?.rows      ?? []
  const capeRows   = capeData?.rows    ?? []
  const laborRows  = laborData?.rows   ?? []
  const goldRows   = (goldData?.rows   ?? []).map(r => ({
    ...r, gold_ret_21d_pct: r.gold_ret_21d != null ? +(r.gold_ret_21d * 100).toFixed(3) : null
  }))
  const riskRows   = (riskData?.rows   ?? []).map(r => ({ ...r, hy_spread_pct: r.hy_spread }))

  const merged = mergeOverlay(priceRows, regimeRows)

  return (
    <div className="history-page">
      {/* Toolbar */}
      <div className="hist-toolbar">
        <h2>Historical Data</h2>
        <div className="hist-controls">
          <div ref={tickerRef} style={{ position: 'relative', minWidth: 280 }}>
            <input
              value={tickerOpen ? tickerSearch : tickerLabel(ticker, availableTickers)}
              onChange={e => { setTickerSearch(e.target.value); setTickerOpen(true) }}
              onFocus={() => { setTickerSearch(''); setTickerOpen(true) }}
              placeholder="Search ticker…"
              style={{ width: '100%', padding: '5px 10px', fontSize: '0.85rem',
                       border: '1px solid #cbd5e1', borderRadius: 6, boxSizing: 'border-box' }}
            />
            {tickerOpen && (
              <div style={{ position: 'absolute', top: '110%', left: 0, right: 0, zIndex: 100,
                            background: '#fff', border: '1px solid #cbd5e1', borderRadius: 6,
                            boxShadow: '0 4px 12px rgba(0,0,0,0.1)', maxHeight: 260, overflowY: 'auto' }}>
                {availableTickers
                  .filter(t => {
                    const q = tickerSearch.toLowerCase()
                    return !q || t.ticker.toLowerCase().includes(q) || (t.name || '').toLowerCase().includes(q)
                  })
                  .map(t => (
                    <div key={t.ticker}
                         onClick={() => { setTicker(t.ticker); setTickerOpen(false); setTickerSearch('') }}
                         style={{ padding: '7px 12px', cursor: 'pointer', fontSize: '0.82rem',
                                  background: t.ticker === ticker ? '#eff6ff' : undefined,
                                  borderBottom: '1px solid #f1f5f9' }}
                         onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
                         onMouseLeave={e => e.currentTarget.style.background = t.ticker === ticker ? '#eff6ff' : ''}>
                      <strong>{t.ticker}</strong>
                      {t.name && t.name !== t.ticker && <span style={{ color: '#64748b', marginLeft: 6 }}>{t.name}</span>}
                      <span style={{ color: '#94a3b8', marginLeft: 6, fontSize: '0.75rem' }}>{t.first.slice(0,4)}–{t.last.slice(0,4)}</span>
                    </div>
                  ))}
              </div>
            )}
          </div>
          <div className="day-btns">
            {DAY_OPTIONS.map(o => (
              <button key={o.days} className={`day-btn ${days === o.days ? 'active' : ''}`}
                      onClick={() => setDays(o.days)}>
                {o.label}
              </button>
            ))}
          </div>
          <button onClick={refetchAll}
                  style={{ marginLeft: 8, padding: '4px 12px', fontSize: '0.8rem',
                           background: '#f1f5f9', border: '1px solid #cbd5e1',
                           borderRadius: 6, cursor: 'pointer' }}>
            Retry
          </button>
        </div>
      </div>
      {anyError && (
        <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 8,
                      padding: '10px 16px', marginBottom: 12, color: '#dc2626', fontSize: '0.85rem' }}>
          Some charts failed to load. Click <strong>Retry</strong> to reload, or refresh the page.
        </div>
      )}

      {/* Cumulative return + regime overlay */}
      <div className="card">
        <SectionHeader title={`${tickerLabel(ticker, availableTickers)} — Cumulative Return (PLN)`}
                       subtitle={ticker + ' · rebased to 0% at period start · dots coloured by regime'} />
        {pl || rl ? <Placeholder loading /> : (pe || re) ? <Placeholder error /> : !merged.length ? <Placeholder /> : (
          <>
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={merged} margin={{ top: 8, right: 20, left: 10, bottom: 44 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis {...makeXAxis(merged, days)} />
                <YAxis tickFormatter={v => (v >= 0 ? '+' : '') + v.toFixed(0) + '%'}
                       tick={{ fontSize: 11 }} width={62} />
                <Tooltip formatter={(v) => typeof v === 'number'
                  ? [(v >= 0 ? '+' : '') + v.toFixed(2) + '%', 'Return (PLN)']
                  : v} labelFormatter={l => l} />
                <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="3 3" />
                <Area type="monotone" dataKey="cum_return_pct" name="Return (PLN)"
                      stroke="#3b82f6" fill="#dbeafe" strokeWidth={1.5} dot={<RegimeDot />} />
              </ComposedChart>
            </ResponsiveContainer>
            <div className="regime-legend">
              {Object.entries(REGIME_COLOR).map(([k, c]) => (
                <span key={k} className="regime-legend-item">
                  <span className="regime-legend-dot" style={{ background: c }} />{REGIME_LABEL[k]}
                </span>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Regime probability stacked */}
      <div className="card">
        <SectionHeader title="Regime Probabilities" subtitle="LightGBM model — stacked to 100%" />
        {rl ? <Placeholder loading /> : re ? <Placeholder error /> : !regimeRows.length ? <Placeholder /> : (
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={regimeRows} margin={{ top: 8, right: 20, left: 10, bottom: 44 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis {...makeXAxis(regimeRows, days)} />
              <YAxis tickFormatter={v => `${(v*100).toFixed(0)}%`} tick={{ fontSize: 11 }} domain={[0,1]} width={40} />
              <Tooltip formatter={(v) => `${(v*100).toFixed(1)}%`} labelFormatter={l => l} />
              <Legend />
              <Area type="monotone" dataKey="prob_risk_on"     name="Risk-on"     stackId="1" stroke={REGIME_COLOR.risk_on}     fill={REGIME_COLOR.risk_on}     fillOpacity={0.75} />
              <Area type="monotone" dataKey="prob_stagflation" name="Stagflation" stackId="1" stroke={REGIME_COLOR.stagflation} fill={REGIME_COLOR.stagflation} fillOpacity={0.75} />
              <Area type="monotone" dataKey="prob_risk_off"    name="Risk-off"    stackId="1" stroke={REGIME_COLOR.risk_off}    fill={REGIME_COLOR.risk_off}    fillOpacity={0.75} />
              <Area type="monotone" dataKey="prob_deflation"   name="Deflation"   stackId="1" stroke={REGIME_COLOR.deflation}   fill={REGIME_COLOR.deflation}   fillOpacity={0.75} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* CPI + Rates */}
      <div className="hist-two-col">
        <div className="card">
          <SectionHeader title="Inflation (CPI YoY)" subtitle="US · Eurozone · Poland" />
          {cl ? <Placeholder loading /> : ce ? <Placeholder error /> : !cpiRows.length ? <Placeholder /> : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={cpiRows} margin={{ top: 8, right: 16, left: 10, bottom: 44 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis {...makeXAxis(cpiRows, days)} />
                <YAxis tickFormatter={v => `${v?.toFixed(1)}%`} tick={{ fontSize: 11 }} width={40} />
                <Tooltip formatter={(v) => v != null ? `${v.toFixed(2)}%` : '—'} labelFormatter={l => l} />
                <ReferenceLine y={2} stroke="#94a3b8" strokeDasharray="4 2"
                               label={{ value: '2%', position: 'right', fontSize: 10, fill: '#94a3b8' }} />
                <Legend />
                <Line type="monotone" dataKey="cpi_us_yoy" name="US"     stroke="#3b82f6" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="cpi_ea_yoy" name="EA"     stroke="#f97316" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="cpi_pl_yoy" name="Poland" stroke="#a855f7" dot={false} strokeWidth={2} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="card">
          <SectionHeader title="Policy Rates" subtitle="Fed Funds · ECB · NBP" />
          {ral ? <Placeholder loading /> : rae ? <Placeholder error /> : !rateRows.length ? <Placeholder /> : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={rateRows} margin={{ top: 8, right: 16, left: 10, bottom: 44 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis {...makeXAxis(rateRows, days)} />
                <YAxis tickFormatter={v => `${v?.toFixed(2)}%`} tick={{ fontSize: 11 }} width={44} />
                <Tooltip formatter={(v) => v != null ? `${v.toFixed(2)}%` : '—'} labelFormatter={l => l} />
                <Legend />
                <Line type="monotone" dataKey="fed_funds_rate" name="Fed Funds" stroke="#3b82f6" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="ecb_rate"       name="ECB"       stroke="#f97316" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="nbp_rate"       name="NBP"       stroke="#a855f7" dot={false} strokeWidth={2} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Risk + FX */}
      <div className="hist-two-col">
        <div className="card">
          <SectionHeader title="Risk Indicators" subtitle="VIX · 10Y–3M yield spread · HY spread (%)" />
          {rsl ? <Placeholder loading /> : rse ? <Placeholder error /> : !riskRows.length ? <Placeholder /> : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={riskRows} margin={{ top: 8, right: 16, left: 10, bottom: 44 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis {...makeXAxis(riskRows, days)} />
                <YAxis tick={{ fontSize: 11 }} width={38} />
                <Tooltip formatter={(v, name) => {
                  if (v == null) return ['—', name]
                  if (name === '10Y–3M') return [`${v.toFixed(2)}%`, name]
                  if (name === 'HY spread') return [`${v.toFixed(2)}%`, name]
                  return [v.toFixed(1), name]
                }} labelFormatter={l => l} />
                <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="3 3" />
                <Legend />
                <Line type="monotone" dataKey="vix_close"     name="VIX"       stroke="#ef4444" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="spread_10y_3m" name="10Y–3M"    stroke="#22c55e" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="hy_spread_pct" name="HY spread" stroke="#f97316" dot={false} strokeWidth={1.5} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="card">
          <SectionHeader title="FX vs PLN" subtitle="USD/PLN · EUR/PLN" />
          {fxl ? <Placeholder loading /> : fxe ? <Placeholder error /> : !fxRows.length ? <Placeholder /> : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={fxRows} margin={{ top: 8, right: 16, left: 10, bottom: 44 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis {...makeXAxis(fxRows, days)} />
                <YAxis tick={{ fontSize: 11 }} domain={['auto','auto']} width={48} />
                <Tooltip formatter={(v) => v != null ? v.toFixed(4) : '—'} labelFormatter={l => l} />
                <Legend />
                <Line type="monotone" dataKey="usdpln" name="USD/PLN" stroke="#3b82f6" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="eurpln" name="EUR/PLN" stroke="#f97316" dot={false} strokeWidth={2} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* CAPE + Labour */}
      <div className="hist-two-col">
        <div className="card">
          <SectionHeader title="Shiller CAPE (PE10)" subtitle="10-year smoothed P/E · expensive above 30 · estimated post-2016" />
          {capl ? <Placeholder loading /> : cape ? <Placeholder error /> : !capeRows.length ? <Placeholder /> : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={capeRows} margin={{ top: 8, right: 16, left: 10, bottom: 44 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis {...makeXAxis(capeRows, days)} />
                <YAxis tick={{ fontSize: 11 }} width={38} />
                <Tooltip formatter={(v, name) => v != null ? [name === 'Implied 10Y ret' ? `${v}%` : v.toFixed(1) + '×', name] : ['—', name]} labelFormatter={l => l} />
                <ReferenceLine y={30} stroke="#f97316" strokeDasharray="4 2"
                               label={{ value: '30× expensive', position: 'right', fontSize: 10, fill: '#f97316' }} />
                <Legend />
                <Line type="monotone" dataKey="cape" name="CAPE (PE10)" stroke="#3b82f6" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="implied_return_q50" name="Implied 10Y ret" stroke="#22c55e" dot={false} strokeWidth={1.5} strokeDasharray="4 2" connectNulls />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="card">
          <SectionHeader title="US Unemployment" subtitle="Sahm rule: rise of 0.5pp from 12M low signals recession" />
          {ll ? <Placeholder loading /> : le ? <Placeholder error /> : !laborRows.length ? <Placeholder /> : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={laborRows} margin={{ top: 8, right: 16, left: 10, bottom: 44 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis {...makeXAxis(laborRows, days)} />
                <YAxis tickFormatter={v => `${v?.toFixed(1)}%`} tick={{ fontSize: 11 }} width={40} />
                <Tooltip formatter={(v) => v != null ? `${v.toFixed(1)}%` : '—'} labelFormatter={l => l} />
                <Legend />
                <Line type="monotone" dataKey="unemployment_us" name="Unemployment" stroke="#3b82f6" dot={false} strokeWidth={2} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Gold 21-day return */}
      <div className="card">
        <SectionHeader title="Gold 21-Day Return (%)" subtitle="Safe-haven signal — positive spikes during risk-off episodes" />
        {gl ? <Placeholder loading /> : ge ? <Placeholder error /> : !goldRows.length ? <Placeholder /> : (
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={goldRows} margin={{ top: 8, right: 20, left: 10, bottom: 44 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis {...makeXAxis(goldRows, days)} />
              <YAxis tickFormatter={v => `${v?.toFixed(1)}%`} tick={{ fontSize: 11 }} width={48} />
              <Tooltip formatter={(v) => v != null ? `${v.toFixed(2)}%` : '—'} labelFormatter={l => l} />
              <ReferenceLine y={0} stroke="#94a3b8" />
              <Area type="monotone" dataKey="gold_ret_21d_pct" name="Gold 21d ret"
                    stroke="#f59e0b" fill="#fef3c7" strokeWidth={1.5} connectNulls />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
