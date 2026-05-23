import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import client from '../api/client'
import { REGIME_COLORS } from '../components/ml/RegimeColors'

function fetchSummary() { return client.get('/ml/summary').then(r => r.data) }

const MODELS = [
  {
    key: 'hmm',
    path: '/ml/hmm',
    titleEn: 'Market Regime',
    titlePl: 'Reżim rynkowy',
    subtitleEn: 'GaussianHMM · 4 states · 155 years',
    subtitlePl: 'GaussianHMM · 4 stany · 155 lat danych',
    descEn: 'Classifies the current market into one of four latent states — Bull, Consolidation, Expensive, or Bear — using 155 years of Shiller data. No human-defined labels. Trained on S&P 500 returns, volatility, CAPE, and yield.',
    descPl: 'Klasyfikuje rynek do jednego z czterech ukrytych stanów — Hossa, Konsolidacja, Drogie akcje, Bessa — na podstawie 155 lat danych Shillera. Bez etykiet narzuconych przez człowieka.',
    charts: 5,
    icon: '🔄',
  },
  {
    key: 'regime_duration',
    path: '/ml/regime-duration',
    titleEn: 'Regime Duration',
    titlePl: 'Czas trwania reżimu',
    subtitleEn: 'Kaplan-Meier survival · episode history',
    subtitlePl: 'Analiza przeżycia Kaplana-Meiera · historia epizodów',
    descEn: 'Given that the market has been in the current regime for T months, what is the probability it continues? Identical mathematics to radioactive decay half-lives.',
    descPl: 'Jeśli rynek jest w bieżącym reżimie od T miesięcy, jakie jest prawdopodobieństwo kontynuacji? Ta sama matematyka co okres połowicznego rozpadu izotopów.',
    charts: 4,
    icon: '⏱',
  },
  {
    key: 'volatility',
    path: '/ml/volatility',
    titleEn: 'Volatility Forecast',
    titlePl: 'Prognoza zmienności',
    subtitleEn: 'Random Forest · HAR-RV features · 21d/63d',
    subtitlePl: 'Random Forest · cechy HAR-RV · horyzont 21d/63d',
    descEn: 'Forecasts how turbulent the next 21 or 63 days will be. Built on the HAR-RV model — a standard in academic vol forecasting — extended with macro features.',
    descPl: 'Prognozuje jak gwałtowny będzie rynek w najbliższych 21 lub 63 dniach. Oparty na modelu HAR-RV rozszerzonym o cechy makroekonomiczne.',
    charts: 4,
    icon: '📊',
  },
  {
    key: 'fx',
    path: '/ml/fx',
    titleEn: 'FX Uncertainty',
    titlePl: 'Ryzyko kursowe',
    subtitleEn: 'LightGBM quantile · USD/PLN · 21d/63d',
    subtitlePl: 'LightGBM kwantylowy · USD/PLN · 21d/63d',
    descEn: 'Shows the range of plausible USD/PLN exchange rates over the next 21 or 63 days. The width of the band is the useful output — the direction is near-random (Meese-Rogoff result).',
    descPl: 'Pokazuje zakres możliwych kursów USD/PLN. Szerokość przedziału to użyteczna informacja — kierunek jest prawie losowy (wynik Meese-Rogoffa).',
    charts: 4,
    icon: '💱',
  },
  {
    key: 'recession',
    path: '/ml/recession',
    titleEn: 'Recession Risk',
    titlePl: 'Ryzyko recesji',
    subtitleEn: 'LightGBM + isotonic calibration · 1960–present',
    subtitlePl: 'LightGBM + kalibracja izotoniczna · 1960–teraz',
    descEn: 'Estimates the probability of a US recession using yield curve, unemployment, industrial production and 8 other leading indicators. Trained on monthly data from 1960 — 7 recessions.',
    descPl: 'Szacuje prawdopodobieństwo recesji w USA na podstawie krzywej rentowności, bezrobocia, produkcji przemysłowej i 8 innych wskaźników. 7 recesji w danych od 1960 r.',
    charts: 4,
    icon: '📉',
  },
  {
    key: 'cape',
    path: '/ml/cape',
    titleEn: 'CAPE Valuation',
    titlePl: 'Wycena CAPE',
    subtitleEn: 'Quantile regression · 145Y Shiller · 10Y returns',
    subtitlePl: 'Regresja kwantylowa · 145 lat Shillera · zwroty 10-letnie',
    descEn: 'At today\'s valuation (CAPE=39), what has history returned over 10 years? The model gives 10th, 50th and 90th percentile estimates based on 145 years of S&P 500 data.',
    descPl: 'Przy obecnej wycenie (CAPE=39), ile historycznie zarabiało się przez 10 lat? Model daje percentyle 10/50/90 na podstawie 145 lat danych S&P 500.',
    charts: 5,
    icon: '📐',
  },
  {
    key: 'pca',
    path: '/ml/pca',
    titleEn: 'Diversification Index',
    titlePl: 'Indeks dywersyfikacji',
    subtitleEn: 'Rolling PCA · 5 assets · 63-day window',
    subtitlePl: 'Kroczące PCA · 5 aktywów · okno 63 dni',
    descEn: 'Measures how independently global equities, gold, bonds, currency and volatility move. In a crisis, all assets correlate — diversification collapses to near zero.',
    descPl: 'Mierzy jak niezależnie poruszają się akcje globalne, złoto, obligacje, waluta i zmienność. W czasie kryzysu wszystko koreluje — dywersyfikacja spada do zera.',
    charts: 4,
    icon: '🔀',
  },
]

function SignalBadge({ modelKey, summary }) {
  if (!summary) return <span style={{ color: '#94a3b8', fontSize: '0.8rem' }}>—</span>

  const s = summary[modelKey]
  if (!s) return null

  if (modelKey === 'hmm') {
    return (
      <span style={{
        background: REGIME_COLORS[s.state] + '20',
        color: REGIME_COLORS[s.state],
        border: `1px solid ${REGIME_COLORS[s.state]}40`,
        borderRadius: 5, padding: '0.2rem 0.6rem',
        fontSize: '0.78rem', fontWeight: 600,
      }}>
        {s.state} · {(s.top_prob * 100).toFixed(0)}%
      </span>
    )
  }
  if (modelKey === 'volatility') {
    return (
      <span style={{ fontSize: '0.8rem', color: s.signal === 'high' ? '#ef4444' : '#22c55e', fontWeight: 600 }}>
        {s.vol_21d_pct != null ? `${s.vol_21d_pct}% ann.` : '—'}
      </span>
    )
  }
  if (modelKey === 'recession') {
    const color = s.prob > 0.3 ? '#ef4444' : s.prob > 0.15 ? '#f97316' : '#22c55e'
    return <span style={{ fontSize: '0.8rem', color, fontWeight: 600 }}>{s.prob != null ? `${(s.prob * 100).toFixed(1)}%` : '—'}</span>
  }
  if (modelKey === 'cape') {
    return <span style={{ fontSize: '0.8rem', color: '#475569', fontWeight: 600 }}>
      CAPE {s.cape} · q50={s.ret_q50_pct}%/yr
    </span>
  }
  if (modelKey === 'pca') {
    const color = s.div_index < 0.4 ? '#ef4444' : s.div_index < 0.55 ? '#f97316' : '#22c55e'
    return <span style={{ fontSize: '0.8rem', color, fontWeight: 600 }}>{s.div_index != null ? s.div_index.toFixed(3) : '—'}</span>
  }
  if (modelKey === 'regime_duration') {
    return <span style={{ fontSize: '0.8rem', color: '#475569', fontWeight: 600 }}>
      {s.current_state} · {s.current_duration_months}m
    </span>
  }
  if (modelKey === 'fx') {
    return <span style={{ fontSize: '0.8rem', color: '#475569', fontWeight: 600 }}>
      {s.usdpln_q10}–{s.usdpln_q90} PLN
    </span>
  }
  return null
}

export default function ML() {
  const { t, i18n } = useTranslation()
  const pl = i18n.language === 'pl'
  const { data: summary, isLoading } = useQuery({ queryKey: ['ml-summary'], queryFn: fetchSummary })

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '1.5rem 1rem' }}>
      <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#0f172a', marginBottom: '0.3rem' }}>
        {pl ? 'Research — modele ML' : 'Research — ML Models'}
      </h1>
      <p style={{ color: '#64748b', marginBottom: '1rem', fontSize: '0.9rem' }}>
        {pl
          ? '7 niezależnych modeli predykcyjnych — każdy odpowiada na inne pytanie. Kliknij model, aby zobaczyć wykresy i szczegóły.'
          : '7 independent predictive models — each answers a different question. Click a model to see charts and details.'}
      </p>

      <div style={{
        marginBottom: '1.75rem',
        padding: '0.85rem 1.1rem',
        background: '#fef3c7',
        borderLeft: '4px solid #f59e0b',
        borderRadius: 6,
        fontSize: '0.82rem',
        lineHeight: 1.55,
        color: '#78350f',
      }}>
        <strong>{pl ? 'Sekcja badawcza.' : 'Research section.'}</strong>{' '}
        {pl
          ? 'Modele poniżej zostały zbudowane jako demonstracja technik ML (HMM, KM, RF, LightGBM, kalibracja izotoniczna, PCA). Nie napędzają one rekomendacji inwestycyjnej aplikacji — ta pozostaje prosta: globalna dywersyfikacja, regularne wpłaty, ignorowanie krótkoterminowych sygnałów. Modele mają ograniczenia (np. HMM nie odróżnia środowiska rynkowego XIX wieku od XXI), opisane na każdej stronie.'
          : 'The models below were built as a demonstration of ML techniques (HMM, KM, RF, LightGBM, isotonic calibration, PCA). They do not drive the app\'s investment recommendation — that remains simple: be globally diversified, contribute monthly, ignore short-term signals. The models have limitations (e.g. the HMM cannot distinguish the 19th-century equity environment from the 21st), documented on each page.'}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: '1rem' }}>
        {MODELS.map(m => (
          <Link key={m.key} to={m.path} style={{ textDecoration: 'none' }}>
            <div style={{
              background: '#fff', borderRadius: 10, border: '1px solid #e2e8f0',
              padding: '1.1rem', cursor: 'pointer', transition: 'box-shadow 0.15s',
            }}
              onMouseEnter={e => e.currentTarget.style.boxShadow = '0 4px 16px #0001'}
              onMouseLeave={e => e.currentTarget.style.boxShadow = 'none'}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
                <div>
                  <span style={{ fontSize: '1.3rem', marginRight: '0.5rem' }}>{m.icon}</span>
                  <span style={{ fontWeight: 700, color: '#0f172a', fontSize: '1rem' }}>
                    {pl ? m.titlePl : m.titleEn}
                  </span>
                </div>
                <SignalBadge modelKey={m.key} summary={summary} />
              </div>
              <div style={{ fontSize: '0.72rem', color: '#94a3b8', marginBottom: '0.5rem', fontFamily: 'monospace' }}>
                {pl ? m.subtitlePl : m.subtitleEn}
              </div>
              <p style={{ fontSize: '0.83rem', color: '#475569', lineHeight: 1.55, margin: 0 }}>
                {pl ? m.descPl : m.descEn}
              </p>
              <div style={{ marginTop: '0.75rem', fontSize: '0.75rem', color: '#94a3b8' }}>
                {m.charts} {pl ? 'wykresów' : 'charts'} →
              </div>
            </div>
          </Link>
        ))}
      </div>

      <div style={{
        marginTop: '2rem', padding: '1.1rem 1.3rem', background: '#f8fafc',
        borderRadius: 8, border: '1px solid #e2e8f0',
      }}>
        <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#334155', margin: '0 0 0.5rem' }}>
          {pl ? 'Co modele mówią łącznie?' : 'What do the models say collectively?'}
        </h3>
        <p style={{ fontSize: '0.82rem', color: '#475569', lineHeight: 1.6, margin: 0 }}>
          {pl
            ? 'Te modele nie są systemem sygnałów transakcyjnych — nie próbuj nimi "wyczuć rynku". Są narzędziem świadomości: pozwalają rozumieć w jakim otoczeniu podejmujesz miesięczną decyzję IKE. Rekomendacja INVEST/DCA/WAIT na stronie Decyzja syntetyzuje te sygnały w jedno zdanie.'
            : 'These models are not a trading signal system — don\'t use them to "time the market." They are a situational awareness tool: they help you understand the environment in which you are making your monthly IKE decision. The INVEST/DCA/WAIT recommendation on the Decision page synthesises these signals into a single sentence.'}
        </p>
      </div>
    </div>
  )
}
