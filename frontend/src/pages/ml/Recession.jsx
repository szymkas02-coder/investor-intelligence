import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  ComposedChart, LineChart, Line, BarChart, Bar, ScatterChart, Scatter,
  Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  ReferenceLine, ReferenceArea,
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

function RecessionBands({ bands = [], children, xDomain }) {
  return (
    <>
      {bands.map((b, i) => (
        <ReferenceArea key={i} x1={b.start} x2={b.end} fill="#94a3b8" fillOpacity={0.15} />
      ))}
      {children}
    </>
  )
}

export default function RecessionPage() {
  const { i18n } = useTranslation()
  const pl = i18n.language === 'pl'

  const { data: history }     = useQuery({ queryKey: ['rec-history'],  queryFn: () => fetch('/ml/recession/history') })
  const { data: features }    = useQuery({ queryKey: ['rec-features'], queryFn: () => fetch('/ml/recession/features') })
  const { data: yieldCurve }  = useQuery({ queryKey: ['rec-yield'],    queryFn: () => fetch('/ml/recession/yield-curve') })
  const { data: calibration } = useQuery({ queryKey: ['rec-calib'],    queryFn: () => fetch('/ml/recession/calibration') })

  // Year-only ticks for the long daily-resolution charts.
  // tickFmt extracts the year; tickProps space them out so labels don't overlap.
  const tickFmt = d => d?.slice(0, 4)
  const dailyTickProps = (rows, fontSize = 10) => {
    // Aim for ~10 labels regardless of row count.
    const n = rows?.length ?? 0
    const desired = 10
    const interval = n > desired ? Math.floor(n / desired) : 0
    return { dataKey: 'date', tickFormatter: tickFmt, tick: { fontSize }, interval, minTickGap: 24 }
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '1.5rem 1rem' }}>
      <BackLink />
      <h1 style={{ fontSize: '1.4rem', fontWeight: 700, color: '#0f172a', marginBottom: '0.2rem' }}>
        📉 {pl ? 'Ryzyko recesji — LightGBM' : 'Recession Risk — LightGBM'}
      </h1>
      <p style={{ color: '#64748b', fontSize: '0.85rem', marginBottom: '1.5rem' }}>
        {pl ? 'Dane FRED 1960–2026 · 7 recesji · kalibracja izotoniczna · Estrella-Mishkin (1998)'
             : 'FRED data 1960–2026 · 7 recessions · isotonic calibration · Estrella-Mishkin (1998)'}
      </p>

      {features && (
        <div style={{ marginBottom: '1.5rem', padding: '0.8rem 1rem', background: '#f0fdf4', borderRadius: 8, border: '1px solid #bbf7d0', fontSize: '0.82rem' }}>
          <strong>Training data:</strong> {features.training_start} – present · {features.n_total_months} months · {features.n_recession_months} recession months ({features.n_total_months ? ((features.n_recession_months / features.n_total_months) * 100).toFixed(1) : '—'}%)
        </div>
      )}

      <ChartCard
        title={pl ? 'Prawdopodobieństwo recesji w czasie' : 'Recession probability over time'}
        plain={pl
          ? 'Niebieska linia = szacowane prawdopodobieństwo recesji. Szare tło = faktyczne recesje USA (NBER). Model powinien rosnąć przed każdym szarym obszarem.'
          : 'Blue line = estimated recession probability. Grey shading = actual US recessions (NBER). The model should rise before each grey period.'}
        technical="LightGBM classifier with scale_pos_weight weighting + isotonic CalibratedClassifierCV (cv=5). Features: yield spread (T10Y3M dominant per Estrella-Mishkin), unemployment, INDPRO, VIX, housing permits, Sahm indicator. Training on monthly data 1960–present."
        chart={
          history?.data ? (
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={history.data} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                <XAxis {...dailyTickProps(history.data)} />
                <YAxis tickFormatter={v => `${(v * 100).toFixed(0)}%`} domain={[0, 1]} tick={{ fontSize: 10 }} />
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <Tooltip formatter={(v, n) => n === 'prob' ? `${(v * 100).toFixed(1)}%` : v} contentStyle={{ fontSize: '0.75rem' }} />
                {(history.recession_bands ?? []).map((b, i) => (
                  <ReferenceArea key={i} x1={b.start} x2={b.end} fill="#94a3b8" fillOpacity={0.2} />
                ))}
                <ReferenceLine y={0.3} stroke="#f97316" strokeDasharray="4 2" label={{ value: '30%', fill: '#f97316', fontSize: 9 }} />
                <ReferenceLine y={0.5} stroke="#ef4444" strokeDasharray="4 2" label={{ value: '50%', fill: '#ef4444', fontSize: 9 }} />
                <Line type="monotone" dataKey="prob" stroke="#3b82f6" strokeWidth={1.5} dot={false} name="Recession prob" />
              </ComposedChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'Krzywa rentowności — spread 10Y-3M' : 'Yield curve — 10Y minus 3M spread'}
        plain={pl
          ? 'Inwersja krzywej rentowności (spread < 0) historycznie poprzedza recesje o 8-12 miesięcy. To najsilniejszy pojedynczy predyktor recesji (Estrella-Mishkin 1998).'
          : 'Yield curve inversion (spread < 0) historically precedes recessions by 8-12 months. It is the single best recession predictor (Estrella-Mishkin 1998).'}
        technical="T10Y3M = 10Y Treasury yield − 3M T-bill yield (FRED daily). Inversion = negative spread. Lead time 8-12 months confirmed in literature. Grey = NBER recession periods."
        chart={
          yieldCurve?.data ? (
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart data={yieldCurve.data} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                <XAxis {...dailyTickProps(yieldCurve.data)} />
                <YAxis tick={{ fontSize: 10 }} label={{ value: 'spread %', angle: -90, position: 'insideLeft', fontSize: 10 }} />
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <Tooltip formatter={v => `${v?.toFixed(2)}%`} contentStyle={{ fontSize: '0.75rem' }} />
                {(yieldCurve.recession_bands ?? []).map((b, i) => (
                  <ReferenceArea key={i} x1={b.start} x2={b.end} fill="#94a3b8" fillOpacity={0.2} />
                ))}
                <ReferenceLine y={0} stroke="#ef4444" strokeWidth={1.5} strokeDasharray="3 2" />
                <Area type="monotone" dataKey="spread" fill="#3b82f640" stroke="#3b82f6" strokeWidth={1.5} name="10Y-3M spread" />
              </ComposedChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'Ważność cech' : 'Feature importance'}
        plain={pl
          ? 'Które wskaźniki model uznaje za najważniejsze. Krzywa rentowności i bezrobocie dominują — to zgodne z literaturą ekonomiczną.'
          : 'Which indicators the model finds most important. Yield curve and unemployment dominate — consistent with economic literature.'}
        technical="LightGBM split gain importance. Top features: spread_10y_3m (Estrella-Mishkin), unemployment_us (Sahm basis), initial_claims (high-frequency LEI), cpi_us_yoy (inflation signal), INDPRO (Conference Board LEI). Sahm/PERMIT/ICSA available from ~2000 only — NaN-filled for 1960-2000."
        chart={
          features?.features?.length ? (
            <ResponsiveContainer width="100%" height={features.features.length * 26 + 30}>
              <BarChart data={features.features} layout="vertical" margin={{ top: 5, right: 30, left: 100, bottom: 5 }}>
                <XAxis type="number" tick={{ fontSize: 10 }} />
                <YAxis type="category" dataKey="feature" tick={{ fontSize: 10 }} width={100} />
                <Tooltip contentStyle={{ fontSize: '0.75rem' }} />
                <Bar dataKey="importance" fill="#ef4444" name="Importance" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'Kalibracja modelu (diagram niezawodności)' : 'Model calibration (reliability diagram)'}
        plain={pl
          ? 'Jeśli model mówi 40% szansy recesji, czy rzeczywiście w ok. 40% przypadków nastąpiła recesja? Dobry model leży na linii 45°.'
          : 'If the model says 40% recession chance, did recession actually follow in ~40% of such cases? A well-calibrated model lies on the 45° line.'}
        technical="Reliability diagram (calibration curve). X = mean predicted probability in each bin. Y = actual recession frequency in that bin. Isotonic calibration (CalibratedClassifierCV) applied post-fit to correct raw LightGBM score distortion."
        chart={
          calibration?.calibration ? (
            <ResponsiveContainer width="100%" height={240}>
              <ScatterChart margin={{ top: 10, right: 20, left: -5, bottom: 20 }}>
                <XAxis dataKey="mean_predicted" type="number" domain={[0, 1]}
                  name="Mean predicted" tickFormatter={v => `${(v * 100).toFixed(0)}%`}
                  label={{ value: 'Predicted probability', position: 'insideBottom', offset: -10, fontSize: 10 }}
                  tick={{ fontSize: 10 }} />
                <YAxis dataKey="actual_frequency" type="number" domain={[0, 1]}
                  name="Actual frequency" tickFormatter={v => `${(v * 100).toFixed(0)}%`}
                  label={{ value: 'Actual frequency', angle: -90, position: 'insideLeft', fontSize: 10 }}
                  tick={{ fontSize: 10 }} />
                <Tooltip
                  content={({ payload }) => payload?.[0] ? (
                    <div style={{ background: '#fff', border: '1px solid #e2e8f0', padding: '0.4rem 0.6rem', fontSize: '0.73rem', borderRadius: 4 }}>
                      <div>Predicted: {(payload[0].payload.mean_predicted * 100).toFixed(1)}%</div>
                      <div>Actual: {(payload[0].payload.actual_frequency * 100).toFixed(1)}%</div>
                      <div style={{ color: '#94a3b8' }}>n={payload[0].payload.n}</div>
                    </div>
                  ) : null}
                />
                <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#94a3b8" strokeDasharray="4 2" label={{ value: 'Perfect', fill: '#94a3b8', fontSize: 9, position: 'insideTopRight' }} />
                <Scatter data={calibration.calibration} fill="#3b82f6" name="Calibration" />
              </ScatterChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />
    </div>
  )
}
