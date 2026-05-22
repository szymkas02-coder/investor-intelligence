import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  LineChart, Line, BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import client from '../../api/client'
import ChartCard from '../../components/ml/ChartCard'
import { REGIME_COLORS } from '../../components/ml/RegimeColors'

const fetch = (path, params) => client.get(path, { params }).then(r => r.data)

function BackLink() {
  return (
    <Link to="/ml" style={{ fontSize: '0.82rem', color: '#64748b', textDecoration: 'none', display: 'block', marginBottom: '1rem' }}>
      ← ML Models
    </Link>
  )
}

function CorrelationHeatmap({ data }) {
  if (!data?.matrix) return null
  const assets = data.assets
  const matMap = {}
  data.matrix.forEach(r => { matMap[`${r.row}|${r.col}`] = r.value })

  const getColor = (v) => {
    if (v == null) return '#f1f5f9'
    const abs = Math.abs(v)
    if (v >= 0) return `rgba(59, 130, 246, ${(abs * 0.85).toFixed(2)})`
    return `rgba(239, 68, 68, ${(abs * 0.85).toFixed(2)})`
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: '0.78rem', margin: '0 auto' }}>
        <thead>
          <tr>
            <th style={{ padding: '0.4rem 0.6rem', color: '#94a3b8' }}></th>
            {assets.map(a => <th key={a} style={{ padding: '0.4rem 0.6rem', color: '#475569', fontWeight: 600, textAlign: 'center' }}>{a}</th>)}
          </tr>
        </thead>
        <tbody>
          {assets.map(row => (
            <tr key={row}>
              <td style={{ padding: '0.4rem 0.6rem', color: '#475569', fontWeight: 600 }}>{row}</td>
              {assets.map(col => {
                const v = matMap[`${row}|${col}`]
                return (
                  <td key={col} style={{
                    padding: '0.5rem 0.8rem', textAlign: 'center', borderRadius: 3,
                    background: getColor(v),
                    color: v != null && Math.abs(v) > 0.5 ? '#fff' : '#334155',
                    fontWeight: v != null && Math.abs(v) > 0.7 ? 700 : 400,
                  }}>
                    {v != null ? v.toFixed(2) : '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ fontSize: '0.72rem', color: '#94a3b8', textAlign: 'center', marginTop: '0.5rem' }}>
        Blue = positive correlation · Red = negative · 63-day rolling window
      </p>
    </div>
  )
}

function BoxPlot({ data }) {
  if (!data?.data) return null
  const bpData = data.data.map(d => ({
    ...d,
    iqr: [d.q25, d.q75],
    full: [d.min, d.max],
  }))

  return (
    <div style={{ display: 'flex', gap: '1.5rem', justifyContent: 'center', flexWrap: 'wrap' }}>
      {bpData.map(d => (
        <div key={d.regime} style={{ textAlign: 'center', minWidth: 100 }}>
          <div style={{ fontSize: '0.75rem', color: REGIME_COLORS[d.regime] || '#6b7280', fontWeight: 600, marginBottom: '0.3rem', textTransform: 'capitalize' }}>
            {d.regime}
          </div>
          <div style={{ display: 'inline-block', width: 32, position: 'relative', height: 100 }}>
            {/* min-max whisker */}
            <div style={{
              position: 'absolute', left: '50%', top: `${(1 - d.max) * 100}%`,
              height: `${(d.max - d.min) * 100}%`, width: 2,
              background: d.color || '#6b7280', transform: 'translateX(-50%)',
            }} />
            {/* IQR box */}
            <div style={{
              position: 'absolute', left: '15%', top: `${(1 - d.q75) * 100}%`,
              height: `${(d.q75 - d.q25) * 100}%`, width: '70%',
              background: (d.color || '#6b7280') + '40',
              border: `2px solid ${d.color || '#6b7280'}`,
              borderRadius: 3,
            }} />
            {/* Median line */}
            <div style={{
              position: 'absolute', left: '15%', top: `${(1 - d.median) * 100}%`,
              height: 2, width: '70%', background: d.color || '#6b7280',
            }} />
          </div>
          <div style={{ fontSize: '0.7rem', color: '#94a3b8', marginTop: '0.3rem' }}>
            median {(d.median * 100).toFixed(0)}%<br />n={d.n}
          </div>
        </div>
      ))}
    </div>
  )
}

export default function PCAPage() {
  const { i18n } = useTranslation()
  const pl = i18n.language === 'pl'

  const { data: history }  = useQuery({ queryKey: ['pca-history'],   queryFn: () => fetch('/ml/pca/history') })
  const { data: corr }     = useQuery({ queryKey: ['pca-corr'],      queryFn: () => fetch('/ml/pca/correlations', { years: 5 }) })
  const { data: byRegime } = useQuery({ queryKey: ['pca-regime'],    queryFn: () => fetch('/ml/pca/by-regime') })
  const { data: heatmap }  = useQuery({ queryKey: ['pca-heatmap'],   queryFn: () => fetch('/ml/pca/current-heatmap') })

  const tickFmt = d => d?.slice(0, 7)

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '1.5rem 1rem' }}>
      <BackLink />
      <h1 style={{ fontSize: '1.4rem', fontWeight: 700, color: '#0f172a', marginBottom: '0.2rem' }}>
        🔀 {pl ? 'Indeks dywersyfikacji — PCA' : 'Diversification Index — PCA'}
      </h1>
      <p style={{ color: '#64748b', fontSize: '0.85rem', marginBottom: '1.5rem' }}>
        {pl ? 'Kroczące PCA · 5 aktywów · okno 63 dni · div_index = 1 − wariancja PC1'
             : 'Rolling PCA · 5 assets · 63-day window · div_index = 1 − PC1 variance explained'}
      </p>

      <ChartCard
        title={pl ? 'Indeks dywersyfikacji w czasie' : 'Diversification index over time'}
        plain={pl
          ? 'Wyższy indeks = aktywa poruszają się bardziej niezależnie = lepsza dywersyfikacja. Kryzys 2020 i 2022 widać jako duże spadki — wszystko korelowało naraz.'
          : 'Higher index = assets move more independently = better diversification. The 2020 and 2022 crises appear as sharp drops — everything correlated at once.'}
        technical="div_index = 1 − PC1_explained_variance. Rolling 63-day PCA on standardised return correlation matrix (5 assets: ACWI, Gold, TLT, USDPLN, VIX). Low div_index → single dominant risk factor (market beta mode). Identical to EOF analysis in atmospheric science."
        chart={
          history?.data ? (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={history.data} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                <XAxis dataKey="date" tickFormatter={tickFmt} tick={{ fontSize: 10 }} interval={119} />
                <YAxis domain={[0, 1]} tickFormatter={v => `${(v * 100).toFixed(0)}%`} tick={{ fontSize: 10 }} />
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <Tooltip formatter={v => v != null ? `${(v * 100).toFixed(1)}%` : '—'} contentStyle={{ fontSize: '0.75rem' }} />
                <ReferenceLine y={0.4} stroke="#ef4444" strokeDasharray="4 2" label={{ value: 'Low div', fill: '#ef4444', fontSize: 9 }} />
                <ReferenceLine y={0.6} stroke="#22c55e" strokeDasharray="4 2" label={{ value: 'High div', fill: '#22c55e', fontSize: 9 }} />
                <Line type="monotone" dataKey="div_index" stroke="#3b82f6" strokeWidth={1.5} dot={false} name="Diversification index" />
              </LineChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'Korelacje par aktywów w czasie' : 'Pairwise asset correlations over time'}
        plain={pl
          ? 'Korelacja między aktywami rośnie w kryzysach — to moment gdy dywersyfikacja przestaje działać. Złoto i obligacje powinny korelować ujemnie z akcjami w spokojnym otoczeniu.'
          : 'Asset correlations spike in crises — that is when diversification fails. Gold and bonds should negatively correlate with equities in calm environments.'}
        technical="Rolling 63-day Pearson correlations. Asset pairs stored in correlation_stats. ACWI/VIX expected to be strongly positive (both react to market stress). ACWI/TLT expected negative in non-inflationary regimes (flight to safety). ACWI/Gold mixed."
        chart={
          corr?.data ? (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={corr.data} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                <XAxis dataKey="date" tickFormatter={tickFmt} tick={{ fontSize: 10 }} interval={59} />
                <YAxis domain={[-1, 1]} tick={{ fontSize: 10 }} />
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <ReferenceLine y={0} stroke="#94a3b8" />
                <Tooltip formatter={v => v?.toFixed(3)} contentStyle={{ fontSize: '0.75rem' }} />
                <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                {corr.data[0] && Object.keys(corr.data[0]).filter(k => k !== 'date').map((pair, i) => (
                  <Line key={pair} type="monotone" dataKey={pair} strokeWidth={1.5} dot={false}
                    stroke={['#22c55e', '#3b82f6', '#f97316', '#a855f7'][i % 4]}
                    name={pair} connectNulls />
                ))}
              </LineChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'PC1 wg reżimu (wykres pudełkowy)' : 'PC1 variance explained by regime'}
        plain={pl
          ? 'W reżimie bessy PC1 tłumaczy więcej wariancji — więcej aktywów porusza się razem (dywersyfikacja spada). Pokazuje, że model HMM i PCA są ze sobą spójne.'
          : 'In bear regime, PC1 explains more variance — more assets move together (diversification collapses). This shows HMM and PCA are internally consistent.'}
        technical="Box-and-whisker plot of PC1 explained variance, grouped by HMM state_label at time of computation. Bear state expected to show highest PC1 (lowest diversification). Stagflation may also show elevated PC1 due to inflation shock correlations."
        chart={<BoxPlot data={byRegime} />}
      />

      <ChartCard
        title={pl ? 'Aktualna macierz korelacji (63 dni)' : 'Current correlation matrix (63-day rolling)'}
        plain={pl
          ? 'Bieżące korelacje między 5 aktywami w modelu. Niebieski = dodatnia korelacja. Czerwony = ujemna. Im mocniejszy kolor, tym silniejsza zależność.'
          : 'Current correlations between the 5 assets in the model. Blue = positive. Red = negative. Stronger colour = stronger relationship.'}
        technical="5×5 Pearson correlation matrix over the most recent 63 trading days. Assets: ACWI (global equities), Gold, TLT (US long bonds proxy), USD/PLN rate, VIX change (fear gauge). Non-portfolio assets (VIX, USD) included as risk proxies."
        chart={<CorrelationHeatmap data={heatmap} />}
      />
    </div>
  )
}
