import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
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

function StatsPill({ label, value, color }) {
  return (
    <div style={{ textAlign: 'center', padding: '0.6rem 1rem', background: color + '15', borderRadius: 8, border: `1px solid ${color}30` }}>
      <div style={{ fontSize: '0.7rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</div>
      <div style={{ fontSize: '1.1rem', fontWeight: 700, color }}>{value}</div>
    </div>
  )
}

function CurrentGauge({ data }) {
  if (!data?.probabilities) return null
  const sorted = [...data.probabilities].sort((a, b) => b.prob - a.prob)
  return (
    <div>
      <div style={{ textAlign: 'center', marginBottom: '1rem' }}>
        <span style={{ fontWeight: 700, fontSize: '1.1rem', color: REGIME_COLORS[data.state] }}>
          {data.state?.toUpperCase()} · {(sorted[0]?.prob * 100).toFixed(0)}%
        </span>
        <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>{data.date}</div>
      </div>
      {sorted.map(p => (
        <div key={p.state} style={{ marginBottom: '0.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', marginBottom: '0.2rem' }}>
            <span style={{ color: p.color, fontWeight: 600 }}>{p.state}</span>
            <span style={{ color: '#475569' }}>{(p.prob * 100).toFixed(1)}%</span>
          </div>
          <div style={{ height: 8, background: '#f1f5f9', borderRadius: 4, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${p.prob * 100}%`, background: p.color, borderRadius: 4, transition: 'width 0.4s' }} />
          </div>
        </div>
      ))}
    </div>
  )
}

function TransitionHeatmap({ data }) {
  if (!data?.matrix) return null
  const states = data.states
  const matMap = {}
  data.matrix.forEach(r => { matMap[`${r.from}|${r.to}`] = r.probability })

  const getColor = (p) => {
    const alpha = Math.round(p * 255)
    return `rgba(59, 130, 246, ${p.toFixed(2)})`
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: '0.78rem', margin: '0 auto' }}>
        <thead>
          <tr>
            <th style={{ padding: '0.4rem 0.7rem', color: '#94a3b8', textAlign: 'left' }}>From ↓ To →</th>
            {states.map(s => (
              <th key={s} style={{ padding: '0.4rem 0.7rem', color: REGIME_COLORS[s], fontWeight: 600, textAlign: 'center' }}>{s}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {states.map(from => (
            <tr key={from}>
              <td style={{ padding: '0.4rem 0.7rem', color: REGIME_COLORS[from], fontWeight: 600 }}>{from}</td>
              {states.map(to => {
                const p = matMap[`${from}|${to}`] ?? 0
                return (
                  <td key={to} style={{
                    padding: '0.5rem 0.8rem', textAlign: 'center', borderRadius: 4,
                    background: getColor(p),
                    color: p > 0.5 ? '#fff' : '#334155',
                    fontWeight: p > 0.7 ? 700 : 400,
                  }}>
                    {(p * 100).toFixed(1)}%
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ fontSize: '0.72rem', color: '#94a3b8', textAlign: 'center', marginTop: '0.5rem' }}>
        Diagonal = probability of staying in the same state next month
      </p>
    </div>
  )
}

export default function HMMPage() {
  const { i18n } = useTranslation()
  const pl = i18n.language === 'pl'

  const { data: history155 } = useQuery({ queryKey: ['hmm-history-full'], queryFn: () => fetch('/ml/hmm/history', { years: 0 }) })
  const { data: history10 }  = useQuery({ queryKey: ['hmm-history-10y'],  queryFn: () => fetch('/ml/hmm/history', { years: 10 }) })
  const { data: probs10 }    = useQuery({ queryKey: ['hmm-probs-10y'],    queryFn: () => fetch('/ml/hmm/probabilities', { years: 10 }) })
  const { data: transitions } = useQuery({ queryKey: ['hmm-transitions'], queryFn: () => fetch('/ml/hmm/transitions') })
  const { data: stats }      = useQuery({ queryKey: ['hmm-stats'],        queryFn: () => fetch('/ml/hmm/state-stats') })
  const { data: current }    = useQuery({ queryKey: ['hmm-current'],      queryFn: () => fetch('/ml/hmm/current') })

  const tickFormatter = (d) => d?.slice(0, 4)

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '1.5rem 1rem' }}>
      <BackLink />
      <h1 style={{ fontSize: '1.4rem', fontWeight: 700, color: '#0f172a', marginBottom: '0.2rem' }}>
        🔄 {pl ? 'Reżim rynkowy — GaussianHMM' : 'Market Regime — GaussianHMM'}
      </h1>
      <p style={{ color: '#64748b', fontSize: '0.85rem', marginBottom: '1rem' }}>
        {pl ? '4 stany · 155 lat danych Shillera · całkowicie nienadzorowany' : '4 states · 155 years of Shiller data · fully unsupervised'}
      </p>

      <div style={{
        marginBottom: '1.5rem',
        padding: '0.85rem 1.1rem',
        background: '#fef3c7',
        borderLeft: '4px solid #f59e0b',
        borderRadius: 6,
        fontSize: '0.82rem',
        lineHeight: 1.55,
        color: '#78350f',
      }}>
        <strong>{pl ? 'Ograniczenia modelu.' : 'Model limitations.'}</strong>{' '}
        {pl
          ? 'Model jest trenowany na pełnym zakresie danych Shillera (1871–dziś). Rynek akcji po 1990 jest strukturalnie inny niż w XIX wieku i pierwszej połowie XX (stopy procentowe, skład sektorowy, skup własnych akcji, globalizacja, dominacja spółek technologicznych). Model traktuje te epoki jako porównywalne — w rzeczywistości nie są. Etykiety stanów ("bull"/"bear"/"stagflation"/"consolidation") przypisano post-hoc według średniej stopy zwrotu w klastrze i mogą nie odpowiadać intuicyjnemu znaczeniu tych słów (np. okres 2011–2020 zostaje przypisany do stanu o najniższym względnym zwrocie w pełnym zakresie historycznym, mimo że był to długi rynek byka). Traktuj tę stronę jako demonstrację techniki HMM, nie jako sygnał inwestycyjny.'
          : 'This model is trained on the full Shiller dataset (1871–present). The post-1990 equity market is structurally different from the 19th century and the first half of the 20th (rates, sector composition, buybacks, globalisation, dominance of technology firms). The model treats these eras as comparable — they are not. State labels ("bull"/"bear"/"stagflation"/"consolidation") are assigned post-hoc by ranking clusters by mean return and may not match the intuitive meaning of those words (e.g. 2011–2020 ends up in the lowest-relative-return cluster across full history, despite being a long bull market). Treat this page as a demonstration of HMM regime detection, not as a market signal.'}
      </div>

      {/* Current state */}
      <ChartCard
        title={pl ? 'Aktualny stan rynku' : 'Current market state'}
        plain={pl
          ? 'Model wskazuje aktualny reżim rynkowy wraz z pewnością (prawdopodobieństwem). Pasek pokazuje jak pewny jest model każdego stanu.'
          : 'The model\'s current regime assessment with confidence (probability) for each of the 4 states.'}
        technical={pl
          ? 'Prawdopodobieństwa posterior z algorytmu Viterbiego. Suma = 1.0. Stagflation = stan z niską stopą zysku i ujemnym excess CAPE yield.'
          : 'Posterior probabilities from the Viterbi forward algorithm. Sum = 1.0. Stagflation = state with low return mean and negative excess CAPE yield.'}
        chart={<CurrentGauge data={current} />}
      />

      {/* 155Y timeline */}
      <ChartCard
        title={pl ? 'Historia reżimów 1880–2026' : 'Regime history 1880–2026'}
        plain={pl
          ? 'Każdy punkt pokazuje, w jakim reżimie był rynek w danym miesiącu na przestrzeni 155 lat. Szare tło = recesja USA (wg NBER).'
          : 'Each point shows the market regime for that month over 155 years. Grey background = US recession (NBER).'}
        technical={pl
          ? 'Model trenowany na pełnym zbiorze (1745 wierszy), forward-filter Viterbiego dla przypisania stanów — bez backward-smoothing. CAPE=39 jest poza rozkładem treningowym — przypisanie do najbliższego klastra.'
          : 'Model trained on full dataset (1,745 rows). Viterbi forward-filter for state assignment — no backward smoothing (no look-ahead). CAPE=39 is outside training distribution — nearest-cluster assignment.'}
        chart={
          history155?.data ? (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={history155.data} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <XAxis dataKey="date" tickFormatter={tickFormatter} tick={{ fontSize: 10 }} interval={119} />
                <YAxis hide />
                <Tooltip
                  formatter={(v, name) => [v, name]}
                  labelFormatter={l => l}
                  contentStyle={{ fontSize: '0.75rem' }}
                />
                {['bull', 'consolidation', 'stagflation', 'bear'].map(s => (
                  <Area key={s} type="stepAfter" dataKey={d => d.state === s ? 1 : 0}
                    fill={REGIME_COLORS[s]} stroke="none" opacity={0.75}
                    stackId="1" name={s} />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      {/* 10Y probability bands */}
      <ChartCard
        title={pl ? 'Prawdopodobieństwa stanów — ostatnie 10 lat' : '4-state probabilities — last 10 years'}
        plain={pl
          ? 'Wykres skumulowany pokazuje jak pewność modelu zmieniała się w czasie. Gdy jeden kolor dominuje, model jest pewny reżimu.'
          : 'Stacked chart shows how model confidence evolved over time. When one colour dominates, the model is confident about the regime.'}
        technical="Posterior state probabilities from the HMM forward algorithm (not Viterbi hard assignment). Sum = 1.0 at each time step."
        chart={
          probs10?.data ? (
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={probs10.data} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <XAxis dataKey="date" tickFormatter={d => d?.slice(0, 7)} tick={{ fontSize: 10 }} interval={23} />
                <YAxis tickFormatter={v => `${(v * 100).toFixed(0)}%`} tick={{ fontSize: 10 }} />
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <Tooltip formatter={(v) => `${(v * 100).toFixed(1)}%`} contentStyle={{ fontSize: '0.75rem' }} />
                <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                {['bull', 'consolidation', 'stagflation', 'bear'].map(s => (
                  <Area key={s} type="monotone" dataKey={s} stackId="1"
                    fill={REGIME_COLORS[s]} stroke={REGIME_COLORS[s]} fillOpacity={0.8} name={s} />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          ) : <div style={{ height: 250, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      {/* State empirical stats */}
      <ChartCard
        title={pl ? 'Charakterystyka stanów — dane empiryczne' : 'State characteristics — empirical data'}
        plain={pl
          ? 'Dla każdego stanu: jaki był średni roczny zwrot, zmienność i CAPE przez historię, gdy model był w tym stanie.'
          : 'For each state: what was the average annual return, volatility, and CAPE historically when the model was in that state.'}
        technical="Computed from HMM state assignments joined with Shiller data. Returns are log-return × 12 × 100 (annualised %). Volatility = rolling 12M std."
        chart={
          stats?.empirical ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '0.75rem' }}>
              {stats.empirical.map(s => (
                <div key={s.state} style={{
                  padding: '0.85rem', borderRadius: 8, border: `2px solid ${s.color}30`,
                  background: s.color + '08',
                }}>
                  <div style={{ fontWeight: 700, color: s.color, marginBottom: '0.5rem', textTransform: 'capitalize' }}>
                    {s.state}
                  </div>
                  <div style={{ fontSize: '0.8rem', color: '#475569' }}>
                    <div>Ret: <strong style={{ color: s.mean_annual_return_pct > 0 ? '#22c55e' : '#ef4444' }}>
                      {s.mean_annual_return_pct > 0 ? '+' : ''}{s.mean_annual_return_pct}%/yr
                    </strong></div>
                    <div>Vol: <strong>{s.mean_annual_vol_pct}%</strong></div>
                    <div>CAPE: <strong>{s.mean_cape}</strong></div>
                    <div style={{ color: '#94a3b8', marginTop: '0.25rem' }}>{s.n_months} months</div>
                  </div>
                </div>
              ))}
            </div>
          ) : <div style={{ height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>Loading...</div>
        }
      />

      {/* Transition matrix */}
      <ChartCard
        title={pl ? 'Macierz przejść (lepkość stanów)' : 'Transition matrix (state persistence)'}
        plain={pl
          ? 'Każda komórka pokazuje: jeśli rynek jest dziś w danym stanie (wiersz), jakie jest prawdopodobieństwo że w przyszłym miesiącu będzie w innym stanie (kolumna). Wartości na przekątnej to "lepkość" — jak długo stany trwają.'
          : 'Each cell: if the market is in state (row) today, what is the probability it transitions to state (column) next month? Diagonal = persistence probability.'}
        technical="Learned transition matrix A from Baum-Welch EM. Entry A[i,j] = P(state_t+1 = j | state_t = i). High diagonal values (>0.95) indicate regime persistence, consistent with monthly Shiller data."
        chart={<TransitionHeatmap data={transitions} />}
      />
    </div>
  )
}
