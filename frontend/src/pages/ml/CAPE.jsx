import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  ScatterChart, Scatter, LineChart, Line, BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  ReferenceLine, ReferenceDot,
} from 'recharts'
import client from '../../api/client'
import ChartCard from '../../components/ml/ChartCard'

const fetch = (path) => client.get(path).then(r => r.data)

function BackLink() {
  return (
    <Link to="/ml" style={{ fontSize: '0.82rem', color: '#64748b', textDecoration: 'none', display: 'block', marginBottom: '1rem' }}>
      ← ML Models
    </Link>
  )
}

function ReturnFan({ signal }) {
  if (!signal?.cape) return null
  const bars = [
    { label: '10th pct', value: signal.q10, color: '#ef4444' },
    { label: '50th pct (median)', value: signal.q50, color: '#f97316' },
    { label: '90th pct', value: signal.q90, color: '#22c55e' },
    { label: 'Base rate (DMS)', value: signal.base_rate, color: '#3b82f6' },
    { label: 'Historical median', value: signal.hist_median_ret, color: '#94a3b8' },
  ]
  return (
    <div>
      <div style={{ textAlign: 'center', marginBottom: '1rem' }}>
        <span style={{ fontSize: '1.2rem', fontWeight: 700, color: '#f97316' }}>CAPE = {signal.cape}</span>
        <span style={{ fontSize: '0.8rem', color: '#94a3b8', marginLeft: '0.5rem' }}>as of {signal.date}</span>
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={bars} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
          <XAxis dataKey="label" tick={{ fontSize: 10 }} />
          <YAxis tickFormatter={v => `${v}%`} tick={{ fontSize: 10 }} />
          <Tooltip formatter={v => `${v?.toFixed(1)}%/yr`} contentStyle={{ fontSize: '0.75rem' }} />
          <ReferenceLine y={0} stroke="#94a3b8" />
          <Bar dataKey="value" name="10Y real return" radius={[3, 3, 0, 0]}>
            {bars.map((b, i) => <Cell key={i} fill={b.color} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function CAPEPage() {
  const { i18n } = useTranslation()
  const pl = i18n.language === 'pl'

  const { data: scatter }   = useQuery({ queryKey: ['cape-scatter'],   queryFn: () => fetch('/ml/cape/scatter') })
  const { data: history }   = useQuery({ queryKey: ['cape-history'],   queryFn: () => fetch('/ml/cape/history') })
  const { data: signal }    = useQuery({ queryKey: ['cape-signal'],    queryFn: () => fetch('/ml/cape/current-signal') })
  const { data: deciles }   = useQuery({ queryKey: ['cape-deciles'],   queryFn: () => fetch('/ml/cape/decile-table') })
  const { data: featPlane } = useQuery({ queryKey: ['cape-featplane'], queryFn: () => fetch('/ml/cape/feature-plane') })

  const tickFmt = d => d?.slice(0, 4)

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '1.5rem 1rem' }}>
      <BackLink />
      <h1 style={{ fontSize: '1.4rem', fontWeight: 700, color: '#0f172a', marginBottom: '0.2rem' }}>
        📐 {pl ? 'Wycena CAPE — Regresja kwantylowa' : 'CAPE Valuation — Quantile Regression'}
      </h1>
      <p style={{ color: '#64748b', fontSize: '0.85rem', marginBottom: '1.5rem' }}>
        {pl ? '145 lat S&P 500 · Shiller PE10 · prognoza zwrotu realnego na 10 lat · Campbell-Shiller (1988)'
             : '145 years S&P 500 · Shiller PE10 · 10Y real return distribution · Campbell-Shiller (1988)'}
      </p>

      <ChartCard
        title={pl ? 'Aktualny sygnał CAPE' : 'Current CAPE signal'}
        plain={pl
          ? `Przy CAPE=${signal?.cape ?? '—'} historyczne 10-letnie realne zwroty mieściły się w pokazanym zakresie. Mediana modelu to ${signal?.q50 ?? '—'}%/rok, ale zakres jest szeroki.`
          : `At CAPE=${signal?.cape ?? '—'}, historical 10-year real returns spanned the shown range. Model median is ${signal?.q50 ?? '—'}%/yr, but the range is wide.`}
        technical="QuantileRegressor (sklearn, α=0.01, solver=highs) at q=0.10, 0.50, 0.90. Features: log(CAPE), real_long_rate = 10Y yield − trailing CPI. Trained on 1871–2016 (145Y), predicted for all dates including post-2016 where actual returns are not yet known."
        chart={<ReturnFan signal={signal} />}
      />

      <ChartCard
        title={pl ? 'CAPE vs 10-letni zwrot realny (1871–2016)' : 'CAPE vs 10-year real return (1871–2016)'}
        plain={pl
          ? 'Kluczowy wykres ekonomii finansowej (Campbell-Shiller 1988). Każdy punkt = jeden miesiąc w historii. Wysoki CAPE → niższe zwroty. Czerwona linia = aktualny CAPE=39.'
          : 'The key chart of financial economics (Campbell-Shiller 1988). Each dot = one month in history. Higher CAPE → lower future returns. Red line = current CAPE=39.'}
        technical="N=1,744 monthly Shiller observations with known 10Y forward returns (up to 2016). Quantile regression lines (q10/q50/q90) from the fitted model. CAPE explains ~40% of variance of 10Y real returns (OOS R²)."
        chart={
          scatter?.scatter ? (
            <ResponsiveContainer width="100%" height={320}>
              <ScatterChart margin={{ top: 10, right: 20, left: -5, bottom: 20 }}>
                <XAxis dataKey="cape" type="number" domain={[4, 50]} name="CAPE"
                  label={{ value: 'CAPE (Shiller PE10)', position: 'insideBottom', offset: -10, fontSize: 10 }}
                  tick={{ fontSize: 10 }} />
                <YAxis dataKey="ret_10y" type="number" domain={[-15, 25]} name="10Y real return %"
                  label={{ value: '10Y real return %/yr', angle: -90, position: 'insideLeft', fontSize: 10 }}
                  tick={{ fontSize: 10 }} />
                <Tooltip
                  content={({ payload }) => payload?.[0] ? (
                    <div style={{ background: '#fff', border: '1px solid #e2e8f0', padding: '0.4rem 0.6rem', fontSize: '0.73rem', borderRadius: 4 }}>
                      <div>CAPE: {payload[0].payload.cape}</div>
                      <div>10Y ret: {payload[0].payload.ret_10y}%/yr</div>
                      <div style={{ color: '#94a3b8' }}>{payload[0].payload.year}</div>
                    </div>
                  ) : null}
                />
                <Scatter data={scatter.scatter} fill="#3b82f680" name="Historical data" />
                {scatter.current_cape != null && (
                  <ReferenceLine x={scatter.current_cape} stroke="#ef4444" strokeWidth={2} strokeDasharray="5 3"
                    label={{ value: `CAPE=${scatter.current_cape}`, position: 'top', fill: '#ef4444', fontSize: 10 }} />
                )}
              </ScatterChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 320, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'Historia CAPE (1871–2026)' : 'CAPE history (1871–2026)'}
        plain={pl
          ? 'CAPE w czasie — widać wyraźnie dot-com bańkę (~45 w 2000), krach 1929 (~30) i obecny poziom ~39. Linie przerywane = średnia i mediana historyczna.'
          : 'CAPE over time — the dot-com bubble (~45 in 2000), 1929 crash (~30) and current level ~39 are clearly visible. Dashed lines = historical mean and median.'}
        technical={`Historical mean: ${history?.historical_mean}, median: ${history?.historical_median}. Current: ${history?.current_cape}. Monthly data from Shiller CSV (1871–present). CAPE = SP500 price / 10-year average real earnings.`}
        chart={
          history?.data ? (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={history.data} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                <XAxis dataKey="date" tickFormatter={tickFmt} tick={{ fontSize: 10 }} interval={119} />
                <YAxis tick={{ fontSize: 10 }} />
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <Tooltip formatter={v => v?.toFixed(1)} contentStyle={{ fontSize: '0.75rem' }} />
                <Line type="monotone" dataKey="cape" stroke="#f97316" strokeWidth={1.5} dot={false} name="CAPE" />
                {history.historical_mean != null && (
                  <ReferenceLine y={history.historical_mean} stroke="#94a3b8" strokeDasharray="4 2"
                    label={{ value: `mean ${history.historical_mean}`, fill: '#94a3b8', fontSize: 9 }} />
                )}
                {history.historical_median != null && (
                  <ReferenceLine y={history.historical_median} stroke="#64748b" strokeDasharray="4 2"
                    label={{ value: `median ${history.historical_median}`, fill: '#64748b', fontSize: 9 }} />
                )}
              </LineChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'Tabela decylów CAPE (Asness 2012)' : 'CAPE decile table (Asness 2012)'}
        plain={pl
          ? 'Historyczny medianowy zwrot dla każdego decyla CAPE. Aktualne CAPE=39 jest w 9. decylu — jednym z najdroższych historycznie.'
          : 'Historical median return for each CAPE decile. Current CAPE=39 is in the 9th decile — among the most expensive historically.'}
        technical="Asness (2012) 'An Old Friend: The Stock Market's Shiller P/E', AQR Capital. Decile boundaries from 1926–2024 US data. Current decile highlighted."
        chart={
          deciles?.table ? (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '0.8rem' }}>
                <thead>
                  <tr style={{ background: '#f8fafc' }}>
                    <th style={{ padding: '0.4rem 0.6rem', textAlign: 'left', color: '#94a3b8', fontWeight: 600, borderBottom: '1px solid #e2e8f0' }}>Decile</th>
                    <th style={{ padding: '0.4rem 0.6rem', textAlign: 'left', color: '#94a3b8', fontWeight: 600, borderBottom: '1px solid #e2e8f0' }}>CAPE max</th>
                    <th style={{ padding: '0.4rem 0.6rem', textAlign: 'left', color: '#94a3b8', fontWeight: 600, borderBottom: '1px solid #e2e8f0' }}>Median return</th>
                    <th style={{ padding: '0.4rem 0.6rem', textAlign: 'left', color: '#94a3b8', fontWeight: 600, borderBottom: '1px solid #e2e8f0' }}>Std</th>
                  </tr>
                </thead>
                <tbody>
                  {deciles.table.map(row => (
                    <tr key={row.decile} style={{
                      background: row.is_current ? '#fef3c7' : 'transparent',
                      borderBottom: '1px solid #f1f5f9',
                    }}>
                      <td style={{ padding: '0.4rem 0.6rem', fontWeight: row.is_current ? 700 : 400 }}>
                        {row.decile}{row.is_current ? ' ← current' : ''}
                      </td>
                      <td style={{ padding: '0.4rem 0.6rem', color: '#475569' }}>{row.cape_max ?? '—'}</td>
                      <td style={{ padding: '0.4rem 0.6rem', color: row.median_return < 3 ? '#ef4444' : row.median_return < 6 ? '#f97316' : '#22c55e', fontWeight: 600 }}>
                        {row.median_return}%/yr
                      </td>
                      <td style={{ padding: '0.4rem 0.6rem', color: '#94a3b8' }}>{row.std}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'Stopa realna vs CAPE (kolorowanie wg zwrotu)' : 'Real rate vs CAPE (coloured by return)'}
        plain={pl
          ? 'Dwie cechy modelu: CAPE (oś X) i realna stopa długoterminowa (oś Y). Kolor = historyczny 10-letni zwrot. Gdy CAPE wysoki I realna stopa wysoka — zwroty najniższe (czerwony).'
          : 'The model\'s two features: CAPE (x) and real long-term rate (y). Colour = historical 10Y return. High CAPE + high real rate = lowest returns (red).'}
        technical="QuantileRegressor uses log(CAPE) and real_long_rate = 10Y yield - trailing CPI YoY. Feature plane shows the 2D interaction. N=600 random sample from training data."
        chart={
          featPlane?.data ? (
            <ResponsiveContainer width="100%" height={280}>
              <ScatterChart margin={{ top: 10, right: 20, left: -5, bottom: 20 }}>
                <XAxis dataKey="cape" type="number" name="CAPE"
                  label={{ value: 'CAPE', position: 'insideBottom', offset: -10, fontSize: 10 }}
                  tick={{ fontSize: 10 }} />
                <YAxis dataKey="real_long_rate" type="number" name="Real long rate"
                  label={{ value: 'Real rate %', angle: -90, position: 'insideLeft', fontSize: 10 }}
                  tick={{ fontSize: 10 }} />
                <Tooltip
                  content={({ payload }) => payload?.[0] ? (
                    <div style={{ background: '#fff', border: '1px solid #e2e8f0', padding: '0.4rem 0.6rem', fontSize: '0.73rem', borderRadius: 4 }}>
                      <div>CAPE: {payload[0].payload.cape}</div>
                      <div>Real rate: {payload[0].payload.real_long_rate}%</div>
                      <div style={{ color: payload[0].payload.color }}>10Y ret: {payload[0].payload.ret_10y}%/yr</div>
                      <div style={{ color: '#94a3b8' }}>{payload[0].payload.year}</div>
                    </div>
                  ) : null}
                />
                <Scatter data={featPlane.data} name="Historical">
                  {featPlane.data.map((d, i) => (
                    <rect key={i} fill={d.color} />
                  ))}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />
    </div>
  )
}
