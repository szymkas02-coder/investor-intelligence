import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import client from '../../api/client'
import ChartCard from '../../components/ml/ChartCard'
import { REGIME_COLORS } from '../../components/ml/RegimeColors'

const fetch = (path) => client.get(path).then(r => r.data)

function BackLink() {
  return (
    <Link to="/ml" style={{ fontSize: '0.82rem', color: '#64748b', textDecoration: 'none', display: 'block', marginBottom: '1rem' }}>
      ← ML Models
    </Link>
  )
}

function CurrentCard({ data }) {
  if (!data?.current_state) return null
  return (
    <div style={{ padding: '1rem', background: REGIME_COLORS[data.current_state] + '12', borderRadius: 8, border: `1px solid ${REGIME_COLORS[data.current_state]}30` }}>
      <div style={{ fontSize: '0.9rem', fontWeight: 700, color: REGIME_COLORS[data.current_state], marginBottom: '0.5rem', textTransform: 'capitalize' }}>
        Current: {data.current_state}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem', fontSize: '0.82rem' }}>
        <div>
          <div style={{ color: '#94a3b8', fontSize: '0.7rem', marginBottom: '0.2rem' }}>Episode age</div>
          <div style={{ fontWeight: 700 }}>{data.current_duration_months} months</div>
        </div>
        <div>
          <div style={{ color: '#94a3b8', fontSize: '0.7rem', marginBottom: '0.2rem' }}>P(still ongoing)</div>
          <div style={{ fontWeight: 700 }}>{data.km_survival_at_current != null ? `${(data.km_survival_at_current * 100).toFixed(0)}%` : '—'}</div>
        </div>
        <div>
          <div style={{ color: '#94a3b8', fontSize: '0.7rem', marginBottom: '0.2rem' }}>Median duration</div>
          <div style={{ fontWeight: 700 }}>{data.median_duration != null ? `${data.median_duration}m` : '—'}</div>
        </div>
      </div>
      {data.km_curve && data.km_curve.length > 0 && (
        <div style={{ marginTop: '1rem' }}>
          <ResponsiveContainer width="100%" height={120}>
            <LineChart data={data.km_curve}>
              <XAxis dataKey="t" label={{ value: 'months', position: 'insideBottom', offset: -2, fontSize: 10 }} tick={{ fontSize: 10 }} />
              <YAxis tickFormatter={v => `${(v * 100).toFixed(0)}%`} domain={[0, 1]} tick={{ fontSize: 10 }} />
              <Tooltip formatter={v => `${(v * 100).toFixed(1)}%`} contentStyle={{ fontSize: '0.75rem' }} />
              <Line type="stepAfter" dataKey="s" stroke={REGIME_COLORS[data.current_state]} strokeWidth={2} dot={false} name="S(t)" />
              {data.current_duration_months != null && (
                <ReferenceLine x={data.current_duration_months} stroke="#94a3b8" strokeDasharray="4 2" label={{ value: 'Now', fontSize: 9 }} />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

function GanttChart({ data }) {
  if (!data?.episodes) return null
  const episodes = data.episodes.slice(-60)
  return (
    <div style={{ overflowX: 'auto' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', minWidth: 500 }}>
        {episodes.map((ep, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.75rem' }}>
            <div style={{ width: 90, textAlign: 'right', color: '#94a3b8', flexShrink: 0 }}>{ep.start}</div>
            <div
              title={`${ep.state} · ${ep.duration_months}m`}
              style={{
                height: 14, borderRadius: 3,
                background: ep.color,
                width: `${Math.max(ep.duration_months * 4, 8)}px`,
                flexShrink: 0,
                opacity: 0.85,
              }}
            />
            <div style={{ color: REGIME_COLORS[ep.state], fontWeight: 600, flexShrink: 0 }}>
              {ep.duration_months}m
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function RegimeDurationPage() {
  const { i18n } = useTranslation()
  const pl = i18n.language === 'pl'

  const { data: survival } = useQuery({ queryKey: ['km-survival'], queryFn: () => fetch('/ml/regime-duration/survival') })
  const { data: episodes } = useQuery({ queryKey: ['km-episodes'], queryFn: () => fetch('/ml/regime-duration/episodes') })
  const { data: current }  = useQuery({ queryKey: ['km-current'],  queryFn: () => fetch('/ml/regime-duration/current') })

  // Build unified timeline for survival curves
  const survivalData = (() => {
    if (!survival?.curves) return []
    const allT = new Set()
    survival.curves.forEach(c => c.points.forEach(p => allT.add(p.t)))
    const tArr = [...allT].sort((a, b) => a - b)
    const lookup = {}
    survival.curves.forEach(c => {
      c.points.forEach(p => {
        if (!lookup[p.t]) lookup[p.t] = { t: p.t }
        lookup[p.t][c.state] = p.survival
        lookup[p.t][`${c.state}_lo`] = p.lower
        lookup[p.t][`${c.state}_hi`] = p.upper
      })
    })
    return tArr.map(t => lookup[t])
  })()

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '1.5rem 1rem' }}>
      <BackLink />
      <h1 style={{ fontSize: '1.4rem', fontWeight: 700, color: '#0f172a', marginBottom: '0.2rem' }}>
        ⏱ {pl ? 'Czas trwania reżimu — Kaplan-Meier' : 'Regime Duration — Kaplan-Meier'}
      </h1>
      <p style={{ color: '#64748b', fontSize: '0.85rem', marginBottom: '1.5rem' }}>
        {pl ? 'Analiza przeżycia epizodów rynkowych · ta sama matematyka co rozkład promieniotwórczy' : 'Survival analysis of market episodes · same mathematics as radioactive decay'}
      </p>

      <ChartCard
        title={pl ? 'Aktualny epizod' : 'Current episode'}
        plain={pl
          ? 'Ile miesięcy trwa bieżący reżim i jak rzadki jest historycznie. Krzywa przeżycia S(t) = prawdopodobieństwo, że epizod jeszcze trwa po t miesiącach.'
          : 'How many months the current regime has been running and how unusual that is historically. S(t) = probability that an episode is still ongoing after t months.'}
        technical="KM estimator: S(t) = Π(1 - d_i/n_i) for all t_i ≤ t. Current episode is right-censored (not yet ended). 95% CI from Greenwood's formula."
        chart={<CurrentCard data={current} />}
      />

      <ChartCard
        title={pl ? 'Krzywe przeżycia (wszystkie stany)' : 'Survival curves (all states)'}
        plain={pl
          ? 'S(t) = prawdopodobieństwo, że epizod danego reżimu trwa jeszcze po t miesiącach. Stroma krzywa = krótkie epizody. Płaska = długotrwały reżim.'
          : 'S(t) = probability an episode of that regime is still ongoing after t months. Steep curve = short episodes. Flat = long-lasting regime.'}
        technical="Kaplan-Meier non-parametric estimator. The current ongoing episode is censored — it contributes to the at-risk count but not the event count. 95% Greenwood CI bands shown."
        chart={
          survivalData.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={survivalData} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                <XAxis dataKey="t" label={{ value: 'months', position: 'insideBottom', offset: -3, fontSize: 10 }} tick={{ fontSize: 10 }} />
                <YAxis tickFormatter={v => `${(v * 100).toFixed(0)}%`} domain={[0, 1]} tick={{ fontSize: 10 }} />
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <Tooltip formatter={v => v != null ? `${(v * 100).toFixed(1)}%` : '—'} contentStyle={{ fontSize: '0.75rem' }} />
                <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                {(survival?.curves ?? []).map(c => (
                  <Line key={c.state} type="stepAfter" dataKey={c.state} stroke={c.color}
                    strokeWidth={2} dot={false} name={c.state} connectNulls />
                ))}
              </LineChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'Historia epizodów (ostatnie 60)' : 'Episode history (last 60)'}
        plain={pl
          ? 'Każdy pasek to jeden epizod — jeden ciągły okres w tym samym stanie rynkowym. Szerokość = czas trwania w miesiącach.'
          : 'Each bar is one episode — one continuous period in the same market state. Width = duration in months.'}
        technical="Episodes extracted from HMM Viterbi path (latest model version only). Contiguous runs of the same state_label = one episode."
        chart={<GanttChart data={episodes} />}
      />

      <ChartCard
        title={pl ? 'Rozkład długości epizodów' : 'Episode duration distribution'}
        plain={pl
          ? 'Histogram: jak długo trwają epizody każdego stanu. Większość epizodów jest krótka — ale zdarzają się bardzo długie.'
          : 'Histogram: how long episodes of each state last. Most are short — but very long ones do occur.'}
        technical="Empirical duration distribution from HMM episode extraction. KM accounts for right-censoring (current episode). Histogram shows completed episodes only."
        chart={
          episodes?.episodes ? (() => {
            const byState = {}
            episodes.episodes.forEach(ep => {
              if (!byState[ep.state]) byState[ep.state] = []
              byState[ep.state].push(ep.duration_months)
            })
            const chartData = []
            for (let t = 1; t <= 120; t += 5) {
              const row = { t }
              Object.keys(byState).forEach(s => {
                row[s] = byState[s].filter(d => d >= t && d < t + 5).length
              })
              if (Object.keys(byState).some(s => row[s] > 0)) chartData.push(row)
            }
            return (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={chartData} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                  <XAxis dataKey="t" label={{ value: 'months', position: 'insideBottom', offset: -3, fontSize: 10 }} tick={{ fontSize: 10 }} />
                  <YAxis label={{ value: 'count', angle: -90, position: 'insideLeft', fontSize: 10 }} tick={{ fontSize: 10 }} />
                  <Tooltip contentStyle={{ fontSize: '0.75rem' }} />
                  <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                  {Object.keys(byState).map(s => (
                    <Bar key={s} dataKey={s} fill={REGIME_COLORS[s]} opacity={0.8} name={s} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            )
          })()
          : <div style={{ height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />
    </div>
  )
}
