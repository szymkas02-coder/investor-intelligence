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

const tickerLabel = (ticker, tickerList) => {
  const found = tickerList?.find(x => x.ticker === ticker)
  return found?.name && found.name !== ticker ? `${found.name} (${ticker})` : ticker
}

const DAY_OPTIONS = [
  { label: '6M',  days: 180  },
  { label: '1Y',  days: 365  },
  { label: '3Y',  days: 1095 },
  { label: '5Y',  days: 1825 },
  { label: '10Y', days: 3650 },
  { label: 'All', days: 9999 },
]

const fetchData = (url) => client.get(url).then(r => r.data)
const fetchTickers = ()             => fetchData('/tickers')
const fetchPrices  = (t, d)         => fetchData(`/history/prices?ticker=${t}&days=${d}`)
const fetchMacro   = (series, d)    => fetchData(`/history/macro?series=${series}&days=${d}`)
const fetchFX      = (d)            => fetchData(`/history/fx?days=${d}`)
const fetchCAPE    = (d)            => fetchData(`/history/cape?days=${d}`)

function makeTickFmt(days) {
  if (days > 365) return (d) => d ? String(new Date(d).getFullYear()) : ''
  return (d) => {
    if (!d) return ''
    const dt = new Date(d)
    return dt.toLocaleString('en', { month: 'short' }) + ' ' + String(dt.getFullYear()).slice(2)
  }
}

function pickTicks(rows, days, n = 10) {
  if (!rows?.length) return []
  if (days > 365) {
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

function withCumulativeReturn(priceRows) {
  const base = priceRows[0]?.price_pln
  return priceRows.map(p => ({
    ...p,
    cum_return_pct: base && p.price_pln != null
                      ? +((p.price_pln / base - 1) * 100).toFixed(2)
                      : null,
  }))
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
  const { t } = useTranslation()
  const msg   = error ? t('common.loadFailed') : loading ? t('common.loading') : t('common.noData')
  const color = error ? '#ef4444' : '#94a3b8'
  return (
    <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color, fontSize: '0.85rem' }}>
      {msg}
    </div>
  )
}

function makeXAxis(rows, days) {
  return {
    dataKey:       'date',
    ticks:         pickTicks(rows, days),
    tickFormatter: makeTickFmt(days),
    tick:          { fontSize: 11 },
    angle:         -30,
    textAnchor:    'end',
    height:        44,
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
  const { data: tickersData } = useQuery({ queryKey: ['tickers'], queryFn: fetchTickers, staleTime: 10 * 60 * 1000 })
  const availableTickers = tickersData ?? []

  const refetchAll = () => {
    ['hp','hrat','hcpi','hrisk','hfx','hcape','hlab','hgold'].forEach(k =>
      queryClient.invalidateQueries({ queryKey: [k] })
    )
  }

  const q = { staleTime: 5 * 60 * 1000, retry: false }
  const { data: priceData,  isLoading: pl,   isError: pe  } = useQuery({ queryKey: ['hp',    ticker, days], queryFn: () => fetchPrices(ticker, days),                            ...q })
  const { data: rateData,   isLoading: ral,  isError: rae } = useQuery({ queryKey: ['hrat',  days],         queryFn: () => fetchMacro('fed_funds_rate,ecb_rate,nbp_rate', days), ...q })
  const { data: cpiData,    isLoading: cl,   isError: ce  } = useQuery({ queryKey: ['hcpi',  days],         queryFn: () => fetchMacro('cpi_us_yoy,cpi_ea_yoy,cpi_pl_yoy', days), ...q })
  const { data: riskData,   isLoading: rsl,  isError: rse } = useQuery({ queryKey: ['hrisk', days],         queryFn: () => fetchMacro('vix_close,spread_10y_3m,hy_spread', days), ...q })
  const { data: fxData,     isLoading: fxl,  isError: fxe } = useQuery({ queryKey: ['hfx',   days],         queryFn: () => fetchFX(days),                                        ...q })
  const { data: capeData,   isLoading: capl, isError: cpe } = useQuery({ queryKey: ['hcape', days],         queryFn: () => fetchCAPE(days),                                      ...q })
  const { data: laborData,  isLoading: ll,   isError: le  } = useQuery({ queryKey: ['hlab',  days],         queryFn: () => fetchMacro('unemployment_us', days),                  ...q })
  const { data: goldData,   isLoading: gl,   isError: ge  } = useQuery({ queryKey: ['hgold', days],         queryFn: () => fetchMacro('gold_ret_21d', days),                     ...q })

  const anyError = pe || rae || ce || rse || fxe || cpe || le || ge

  const priceRows  = priceData?.rows  ?? []
  const rateRows   = rateData?.rows   ?? []
  const cpiRows    = cpiData?.rows    ?? []
  const fxRows     = fxData?.rows     ?? []
  const capeRows   = capeData?.rows   ?? []
  const laborRows  = laborData?.rows  ?? []
  const goldRows   = (goldData?.rows  ?? []).map(r => ({
    ...r, gold_ret_21d_pct: r.gold_ret_21d != null ? +(r.gold_ret_21d * 100).toFixed(3) : null
  }))
  const riskRows   = (riskData?.rows  ?? []).map(r => ({ ...r, hy_spread_pct: r.hy_spread }))
  const merged     = withCumulativeReturn(priceRows)

  return (
    <div className="history-page">
      {/* Toolbar */}
      <div className="hist-toolbar">
        <h2>{t('history.title')}</h2>
        <div className="hist-controls">
          <div ref={tickerRef} style={{ position: 'relative', minWidth: 280 }}>
            <input
              value={tickerOpen ? tickerSearch : tickerLabel(ticker, availableTickers)}
              onChange={e => { setTickerSearch(e.target.value); setTickerOpen(true) }}
              onFocus={() => { setTickerSearch(''); setTickerOpen(true) }}
              placeholder={t('history.searchTicker')}
              style={{ width: '100%', padding: '5px 10px', fontSize: '0.85rem',
                       border: '1px solid #cbd5e1', borderRadius: 6, boxSizing: 'border-box' }}
            />
            {tickerOpen && (
              <div style={{ position: 'absolute', top: '110%', left: 0, right: 0, zIndex: 100,
                            background: '#fff', border: '1px solid #cbd5e1', borderRadius: 6,
                            boxShadow: '0 4px 12px rgba(0,0,0,0.1)', maxHeight: 260, overflowY: 'auto' }}>
                {availableTickers
                  .filter(item => {
                    const q = tickerSearch.toLowerCase()
                    return !q || item.ticker.toLowerCase().includes(q) || (item.name || '').toLowerCase().includes(q)
                  })
                  .map(item => (
                    <div key={item.ticker}
                         onClick={() => { setTicker(item.ticker); setTickerOpen(false); setTickerSearch('') }}
                         style={{ padding: '7px 12px', cursor: 'pointer', fontSize: '0.82rem',
                                  background: item.ticker === ticker ? '#eff6ff' : undefined,
                                  borderBottom: '1px solid #f1f5f9' }}
                         onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
                         onMouseLeave={e => e.currentTarget.style.background = item.ticker === ticker ? '#eff6ff' : ''}>
                      <strong>{item.ticker}</strong>
                      {item.name && item.name !== item.ticker && <span style={{ color: '#64748b', marginLeft: 6 }}>{item.name}</span>}
                      <span style={{ color: '#94a3b8', marginLeft: 6, fontSize: '0.75rem' }}>{item.first?.slice(0,4)}–{item.last?.slice(0,4)}</span>
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
            {t('common.retry')}
          </button>
        </div>
      </div>

      {anyError && (
        <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 8,
                      padding: '10px 16px', marginBottom: 12, color: '#dc2626', fontSize: '0.85rem' }}>
          {t('common.someChartsFailed')}
        </div>
      )}

      {/* Cumulative return + regime overlay */}
      <div className="card">
        <SectionHeader
          title={`${tickerLabel(ticker, availableTickers)} — ${t('history.cumulativeReturn')}`}
          subtitle={`${ticker} · ${t('history.cumulativeSubtitle')}`}
        />
        {pl ? <Placeholder loading /> : pe ? <Placeholder error /> : !merged.length ? <Placeholder /> : (
          <>
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={merged} margin={{ top: 8, right: 20, left: 10, bottom: 44 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis {...makeXAxis(merged, days)} />
                <YAxis tickFormatter={v => (v >= 0 ? '+' : '') + v.toFixed(0) + '%'} tick={{ fontSize: 11 }} width={62} />
                <Tooltip formatter={(v) => typeof v === 'number'
                  ? [(v >= 0 ? '+' : '') + v.toFixed(2) + '%', t('history.returnPln')]
                  : v} labelFormatter={l => l} />
                <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="3 3" />
                <Area type="monotone" dataKey="cum_return_pct" name={t('history.returnPln')}
                      stroke="#3b82f6" fill="#dbeafe" strokeWidth={1.5} />
              </ComposedChart>
            </ResponsiveContainer>
          </>
        )}
      </div>

      {/* CPI + Rates */}
      <div className="hist-two-col">
        <div className="card">
          <SectionHeader title={t('history.inflationTitle')} subtitle={t('history.inflationSubtitle')} />
          {cl ? <Placeholder loading /> : ce ? <Placeholder error /> : !cpiRows.length ? <Placeholder /> : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={cpiRows} margin={{ top: 8, right: 16, left: 10, bottom: 44 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis {...makeXAxis(cpiRows, days)} />
                <YAxis tickFormatter={v => `${v?.toFixed(1)}%`} tick={{ fontSize: 11 }} width={40} />
                <Tooltip formatter={(v) => v != null ? `${v.toFixed(2)}%` : '—'} labelFormatter={l => l} />
                <ReferenceLine y={2} stroke="#94a3b8" strokeDasharray="4 2"
                               label={{ value: t('history.targetLine'), position: 'right', fontSize: 10, fill: '#94a3b8' }} />
                <Legend />
                <Line type="monotone" dataKey="cpi_us_yoy" name="US"                  stroke="#3b82f6" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="cpi_ea_yoy" name="EA"                  stroke="#f97316" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="cpi_pl_yoy" name={t('history.poland')} stroke="#a855f7" dot={false} strokeWidth={2} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="card">
          <SectionHeader title={t('history.ratesTitle')} subtitle={t('history.ratesSubtitle')} />
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
          <SectionHeader title={t('history.riskTitle')} subtitle={t('history.riskSubtitle')} />
          {rsl ? <Placeholder loading /> : rse ? <Placeholder error /> : !riskRows.length ? <Placeholder /> : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={riskRows} margin={{ top: 8, right: 16, left: 10, bottom: 44 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis {...makeXAxis(riskRows, days)} />
                <YAxis tick={{ fontSize: 11 }} width={38} />
                <Tooltip formatter={(v, name) => {
                  if (v == null) return ['—', name]
                  if (name === '10Y–3M' || name === 'Spread HY') return [`${v.toFixed(2)}%`, name]
                  return [v.toFixed(1), name]
                }} labelFormatter={l => l} />
                <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="3 3" />
                <Legend />
                <Line type="monotone" dataKey="vix_close"     name="VIX"           stroke="#ef4444" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="spread_10y_3m" name="10Y–3M"         stroke="#22c55e" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="hy_spread_pct" name="Spread HY"      stroke="#f97316" dot={false} strokeWidth={1.5} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="card">
          <SectionHeader title={t('history.fxTitle')} subtitle={t('history.fxSubtitle')} />
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
          <SectionHeader title={t('history.capeTitle')} subtitle={t('history.capeSubtitle')} />
          {capl ? <Placeholder loading /> : cpe ? <Placeholder error /> : !capeRows.length ? <Placeholder /> : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={capeRows} margin={{ top: 8, right: 16, left: 10, bottom: 44 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis {...makeXAxis(capeRows, days)} />
                <YAxis tick={{ fontSize: 11 }} width={38} />
                <Tooltip formatter={(v, name) => v != null ? [name === t('history.implied10y') ? `${v}%` : v.toFixed(1) + '×', name] : ['—', name]} labelFormatter={l => l} />
                <ReferenceLine y={30} stroke="#f97316" strokeDasharray="4 2"
                               label={{ value: t('history.expensiveLabel'), position: 'right', fontSize: 10, fill: '#f97316' }} />
                <Legend />
                <Line type="monotone" dataKey="cape"             name="CAPE (PE10)"           stroke="#3b82f6" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="implied_return_q50" name={t('history.implied10y')} stroke="#22c55e" dot={false} strokeWidth={1.5} strokeDasharray="4 2" connectNulls />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="card">
          <SectionHeader title={t('history.unemploymentTitle')} subtitle={t('history.unemploymentSubtitle')} />
          {ll ? <Placeholder loading /> : le ? <Placeholder error /> : !laborRows.length ? <Placeholder /> : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={laborRows} margin={{ top: 8, right: 16, left: 10, bottom: 44 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis {...makeXAxis(laborRows, days)} />
                <YAxis tickFormatter={v => `${v?.toFixed(1)}%`} tick={{ fontSize: 11 }} width={40} />
                <Tooltip formatter={(v) => v != null ? `${v.toFixed(1)}%` : '—'} labelFormatter={l => l} />
                <Legend />
                <Line type="monotone" dataKey="unemployment_us" name={t('history.unemployment')} stroke="#3b82f6" dot={false} strokeWidth={2} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Gold */}
      <div className="card">
        <SectionHeader title={t('history.goldTitle')} subtitle={t('history.goldSubtitle')} />
        {gl ? <Placeholder loading /> : ge ? <Placeholder error /> : !goldRows.length ? <Placeholder /> : (
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={goldRows} margin={{ top: 8, right: 20, left: 10, bottom: 44 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis {...makeXAxis(goldRows, days)} />
              <YAxis tickFormatter={v => `${v?.toFixed(1)}%`} tick={{ fontSize: 11 }} width={48} />
              <Tooltip formatter={(v) => v != null ? `${v.toFixed(2)}%` : '—'} labelFormatter={l => l} />
              <ReferenceLine y={0} stroke="#94a3b8" />
              <Area type="monotone" dataKey="gold_ret_21d_pct" name={t('history.gold21d')}
                    stroke="#f59e0b" fill="#fef3c7" strokeWidth={1.5} connectNulls />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
