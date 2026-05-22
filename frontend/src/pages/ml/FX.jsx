import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  ComposedChart, LineChart, Line, BarChart, Bar, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import client from '../../api/client'
import ChartCard from '../../components/ml/ChartCard'

const fetch = (path, params) => client.get(path, { params }).then(r => r.data)

function BackLink() {
  return (
    <Link to="/ml" style={{ fontSize: '0.82rem', color: '#64748b', textDecoration: 'none', display: 'block', marginBottom: '1rem' }}>
      ← ML Models
    </Link>
  )
}

export default function FXPage() {
  const { i18n } = useTranslation()
  const pl = i18n.language === 'pl'

  const { data: fan }     = useQuery({ queryKey: ['fx-fan'],       queryFn: () => fetch('/ml/fx/fan-chart', { years: 3 }) })
  const { data: errors }  = useQuery({ queryKey: ['fx-errors'],    queryFn: () => fetch('/ml/fx/error-distribution') })
  const { data: band }    = useQuery({ queryKey: ['fx-band'],      queryFn: () => fetch('/ml/fx/band-width', { years: 5 }) })
  const { data: features} = useQuery({ queryKey: ['fx-features'],  queryFn: () => fetch('/ml/fx/features') })

  const tickFmt = d => d?.slice(0, 7)

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '1.5rem 1rem' }}>
      <BackLink />
      <h1 style={{ fontSize: '1.4rem', fontWeight: 700, color: '#0f172a', marginBottom: '0.2rem' }}>
        💱 {pl ? 'Ryzyko kursowe — LightGBM kwantylowy' : 'FX Uncertainty — LightGBM Quantile'}
      </h1>
      <p style={{ color: '#64748b', fontSize: '0.85rem', marginBottom: '1.5rem' }}>
        {pl ? 'USD/PLN · horyzonty 21d i 63d · szerokość przedziału = użyteczna informacja · Meese-Rogoff (1983)'
             : 'USD/PLN · 21d and 63d horizons · band width = useful signal · Meese-Rogoff (1983)'}
      </p>

      <div style={{ marginBottom: '1.5rem', padding: '0.8rem 1rem', background: '#fef3c7', borderRadius: 8, border: '1px solid #fde68a', fontSize: '0.82rem' }}>
        <strong>Note:</strong> {pl
          ? 'Kierunek kursu walutowego jest bliski losowemu na horyzontach 21+ dni (wynik Meese-Rogoffa, 1983). Model nie przewiduje kierunku — prezentuje szerokość niepewności.'
          : 'FX direction is near-random at 21+ day horizons (Meese-Rogoff result, 1983). This model does not forecast direction — it quantifies the uncertainty band.'}
      </div>

      <ChartCard
        title={pl ? 'Kurs USD/PLN — wykres wachlarzowy' : 'USD/PLN — fan chart'}
        plain={pl
          ? 'Czarna linia = kurs historyczny. Pomarańczowe pasmo = przedział 10.–90. percentyl prognoz na 21 dni. Szerszy pasek = większa niepewność.'
          : 'Black line = historical rate. Orange band = 10th–90th percentile of 21-day forecasts. Wider band = greater uncertainty.'}
        technical="LightGBM quantile regression (q=0.10, 0.50, 0.90) with objective='quantile'. Features: rate_differential (UIP theory), cpi_differential (PPP), usdpln_ret_21d (momentum), vix_close, acwi_ret_21d, spread_10y_3m, hy_spread. Walk-forward CV gap = 21 days."
        chart={
          fan?.data ? (
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={fan.data} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                <XAxis dataKey="date" tickFormatter={tickFmt} tick={{ fontSize: 10 }} interval={29} />
                <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10 }} />
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <Tooltip formatter={(v, n) => [v?.toFixed(4), n]} contentStyle={{ fontSize: '0.75rem' }} />
                <Area type="monotone" dataKey="q90" fill="#f97316" stroke="none" fillOpacity={0.2} name="Q90 (PLN weak)" />
                <Area type="monotone" dataKey="q10" fill="#fff" stroke="none" fillOpacity={1} name="Q10 (PLN strong)" legendType="none" />
                <Line type="monotone" dataKey="actual" stroke="#1e293b" strokeWidth={1.5} dot={false} name="Actual USD/PLN" />
                <Line type="monotone" dataKey="q50" stroke="#f97316" strokeWidth={1.5} strokeDasharray="4 2" dot={false} name="Q50 forecast" />
              </ComposedChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'Szerokość pasma niepewności w czasie' : 'Uncertainty band width over time'}
        plain={pl
          ? 'Szerokość przedziału (Q90 − Q10) rośnie w czasie kryzysu (2020, 2022). To sygnał ostrzegawczy — nie kierunek, ale skala ryzyka walutowego.'
          : 'Band width (Q90 − Q10) spikes during crises (2020, 2022). This is a risk warning — not direction, but the magnitude of FX risk.'}
        technical="band_width = rate_upper − rate_lower (PLN per USD). 21d and 63d horizons shown. Wider band in risk-off periods reflects higher conditional variance — PLN is a high-beta EM currency."
        chart={
          band?.data ? (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={band.data} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                <XAxis dataKey="date" tickFormatter={tickFmt} tick={{ fontSize: 10 }} interval={59} />
                <YAxis tick={{ fontSize: 10 }} />
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <Tooltip formatter={v => v?.toFixed(4)} contentStyle={{ fontSize: '0.75rem' }} />
                <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                <Line type="monotone" dataKey="band_width_21" stroke="#f97316" strokeWidth={1.5} dot={false} name="21d band" />
                <Line type="monotone" dataKey="band_width_63" stroke="#3b82f6" strokeWidth={1.5} dot={false} name="63d band" />
              </LineChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'Rozkład błędów prognozy' : 'Forecast error distribution'}
        plain={pl
          ? 'Histogram różnicy (faktyczny kurs − prognoza mediany). Dobrze skalibrowany model: rozkład symetryczny wyśrodkowany na zero. Grube ogony = zdarzenia ekstremalne.'
          : 'Histogram of (actual rate − median forecast). Well-calibrated model: symmetric distribution centred at zero. Fat tails = extreme events.'}
        technical="Error = USDPLN[t+21] − rate_point[t]. Computed by forward-shifting actual rates and computing ex-post residuals. Gaussian kernel density would show fat tails — consistent with Meese-Rogoff: conditional mean near zero, variance meaningful."
        chart={
          errors?.h21 ? (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={errors.h21} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                <XAxis dataKey="bin_center" tickFormatter={v => v?.toFixed(2)} tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <Tooltip formatter={v => v} contentStyle={{ fontSize: '0.75rem' }} />
                <ReferenceLine x={0} stroke="#ef4444" strokeDasharray="3 2" />
                <Bar dataKey="count" fill="#3b82f6" opacity={0.8} name="Count (21d)" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      <ChartCard
        title={pl ? 'Ważność cech' : 'Feature importance'}
        plain={pl
          ? 'Różnica stóp procentowych (teoria UIP) i ostatni trend kursu dominują. VIX i spread kredytowy = globalne ryzyko → przepływy do/z PLN.'
          : 'Interest rate differential (UIP theory) and recent FX momentum dominate. VIX and credit spread = global risk → PLN flows.'}
        technical="LightGBM split gain importance (q50 model, 21d horizon). UIP: rate_differential = fed_funds − nbp_rate. PPP: cpi_differential = cpi_us_yoy − cpi_pl_yoy. usdpln_ret_21d intentionally included (momentum); raw level excluded (would make model trivially predict 'barely moves')."
        chart={
          features?.features?.length ? (
            <ResponsiveContainer width="100%" height={features.features.length * 26 + 30}>
              <BarChart data={features.features} layout="vertical" margin={{ top: 5, right: 30, left: 100, bottom: 5 }}>
                <XAxis type="number" tick={{ fontSize: 10 }} />
                <YAxis type="category" dataKey="feature" tick={{ fontSize: 10 }} width={100} />
                <Tooltip contentStyle={{ fontSize: '0.75rem' }} />
                <Bar dataKey="importance" fill="#f97316" name="Importance" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />
    </div>
  )
}
