import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  ComposedChart, LineChart, Line, BarChart, Bar, ScatterChart, Scatter,
  Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
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

export default function VolatilityPage() {
  const { i18n } = useTranslation()
  const pl = i18n.language === 'pl'

  const { data: forecast } = useQuery({ queryKey: ['vol-forecast'], queryFn: () => fetch('/ml/volatility/forecast', { years: 5 }) })
  const { data: horizons } = useQuery({ queryKey: ['vol-horizons'], queryFn: () => fetch('/ml/volatility/horizons', { years: 3 }) })
  const { data: features } = useQuery({ queryKey: ['vol-features'], queryFn: () => fetch('/ml/volatility/features') })
  const { data: vix }      = useQuery({ queryKey: ['vol-vix'],      queryFn: () => fetch('/ml/volatility/vix-scatter') })

  const tickFmt = d => d?.slice(0, 7)

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '1.5rem 1rem' }}>
      <BackLink />
      <h1 style={{ fontSize: '1.4rem', fontWeight: 700, color: '#0f172a', marginBottom: '0.2rem' }}>
        📊 {pl ? 'Prognoza zmienności — Random Forest' : 'Volatility Forecast — Random Forest'}
      </h1>
      <p style={{ color: '#64748b', fontSize: '0.85rem', marginBottom: '1.5rem' }}>
        {pl ? 'Model HAR-RV z cechami makro · horyzonty 21d i 63d · benchmark: RF lepszy od GARCH o 8.2%'
             : 'HAR-RV model with macro features · 21d and 63d horizons · benchmark: RF beats GARCH by 8.2%'}
      </p>

      <ChartCard
        title={pl ? 'Prognoza vs rzeczywista zmienność (21d)' : 'Forecast vs actual volatility (21d)'}
        plain={pl
          ? 'Pomarańczowa linia = prognoza modelu. Niebieska = faktyczna zmienność. Pasek = 80% przedział ufności (10.–90. percentyl lasu).'
          : 'Orange line = model forecast. Blue = actual realised volatility. Band = 80% confidence interval (10th–90th percentile of RF leaf nodes).'}
        technical="HAR-RV features: vol_21d (monthly lag), vol_5d (weekly), vol_1d (daily proxy), vol_63d (quarterly). Macro overlay: VIX, yield spread, ACWI returns, PLN vol. Walk-forward CV: 5 TimeSeriesSplit folds. Confidence interval from leaf-node distribution across 200 trees."
        chart={
          forecast?.data ? (
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={forecast.data} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                <XAxis dataKey="date" tickFormatter={tickFmt} tick={{ fontSize: 10 }} interval={89} />
                <YAxis tickFormatter={v => `${v}%`} tick={{ fontSize: 10 }} />
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <Tooltip formatter={(v, n) => [v != null ? `${v}%` : '—', n]} contentStyle={{ fontSize: '0.75rem' }} labelFormatter={l => l} />
                <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                <Area type="monotone" dataKey="upper" fill="#f97316" stroke="none" fillOpacity={0.15} name="80% CI upper" legendType="none" />
                <Area type="monotone" dataKey="lower" fill="#fff" stroke="none" fillOpacity={1} name="80% CI lower" legendType="none" />
                <Line type="monotone" dataKey="actual" stroke="#3b82f6" strokeWidth={1.5} dot={false} name="Actual vol" />
                <Line type="monotone" dataKey="forecast" stroke="#f97316" strokeWidth={2} dot={false} name="RF forecast" />
              </ComposedChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'Porównanie horyzontów: 21d vs 63d' : 'Horizon comparison: 21d vs 63d'}
        plain={pl
          ? '21-dniowa prognoza (miesięczna) jest bardziej reaktywna. 63-dniowa (kwartalna) jest wygładzona — wychodzi poza chwilowe skoki zmienności.'
          : 'The 21-day forecast is more reactive. The 63-day (quarterly) is smoother — it looks through short-term vol spikes.'}
        technical="Two separate RF models, same feature set. 63d model uses longer lags (vol_63d, vol_21d as short-horizon feature). Walk-forward gap = 63 days between train and validation."
        chart={
          horizons?.data ? (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={horizons.data} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                <XAxis dataKey="date" tickFormatter={tickFmt} tick={{ fontSize: 10 }} interval={59} />
                <YAxis tickFormatter={v => `${v}%`} tick={{ fontSize: 10 }} />
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <Tooltip formatter={(v) => v != null ? `${v}%` : '—'} contentStyle={{ fontSize: '0.75rem' }} />
                <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                <Line type="monotone" dataKey="vol_21d" stroke="#f97316" strokeWidth={2} dot={false} name="21d forecast" />
                <Line type="monotone" dataKey="vol_63d" stroke="#3b82f6" strokeWidth={2} dot={false} name="63d forecast" />
              </LineChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'Ważność cech (feature importance)' : 'Feature importance'}
        plain={pl
          ? 'Które cechy model uważa za najważniejsze do prognozowania zmienności. VIX i poprzednia zmienność dominują — to oczekiwane.'
          : 'Which features the model finds most useful for forecasting volatility. VIX and lagged volatility dominate — this is expected.'}
        technical="Mean decrease in impurity (MDI) from sklearn RandomForestRegressor. Top features confirm HAR structure: vol lags dominate, VIX adds market-implied vol signal, macro features add regime context."
        chart={
          features?.features?.length ? (
            <ResponsiveContainer width="100%" height={features.features.length * 28 + 30}>
              <BarChart data={features.features} layout="vertical" margin={{ top: 5, right: 30, left: 80, bottom: 5 }}>
                <XAxis type="number" tick={{ fontSize: 10 }} />
                <YAxis type="category" dataKey="feature" tick={{ fontSize: 10 }} width={80} />
                <Tooltip formatter={v => v.toFixed(4)} contentStyle={{ fontSize: '0.75rem' }} />
                <Bar dataKey="importance" fill="#3b82f6" name="Importance" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'VIX vs prognoza zmienności (wg reżimu)' : 'VIX vs vol forecast (by regime)'}
        plain={pl
          ? 'Każdy punkt to jeden dzień: VIX (oś X) vs prognozowana zmienność (oś Y). Kolor = reżim rynkowy w tamtym czasie. Model używa VIX ale wykracza poza prostą korelację dzięki cechom makro.'
          : 'Each dot is one day: VIX (x-axis) vs vol forecast (y-axis). Colour = market regime. The model uses VIX but goes beyond a simple correlation thanks to macro features.'}
        technical="Scatter of N=500 random sample (seeded). VIX is the single strongest predictor of near-term vol. Regime colouring shows the macro context layer — same VIX can imply different forecasts in different regimes."
        chart={
          vix?.data ? (
            <ResponsiveContainer width="100%" height={280}>
              <ScatterChart margin={{ top: 5, right: 20, left: -10, bottom: 5 }}>
                <XAxis dataKey="vix" name="VIX" tick={{ fontSize: 10 }} label={{ value: 'VIX', position: 'insideBottom', offset: -3, fontSize: 10 }} />
                <YAxis dataKey="vol_forecast_pct" name="Vol forecast %" tick={{ fontSize: 10 }} label={{ value: 'Vol %', angle: -90, position: 'insideLeft', fontSize: 10 }} />
                <Tooltip formatter={(v, n) => [typeof v === 'number' ? v.toFixed(2) : v, n]} contentStyle={{ fontSize: '0.75rem' }} />
                <Scatter data={vix.data} name="Observations">
                  {vix.data.map((d, i) => (
                    <rect key={i} fill={d.color} fillOpacity={0.6} />
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
