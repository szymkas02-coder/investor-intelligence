import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import client from '../api/client'
import { REGIME_COLORS } from '../components/ml/RegimeColors'

const fetch = (path) => client.get(path).then(r => r.data).catch(() => null)

const ACTION_COLOR = { INVEST: '#22c55e', DCA: '#f97316', WAIT: '#ef4444' }

function Badge({ children, color, bg }) {
  return (
    <span style={{
      background: bg ?? (color + '15'),
      color: color,
      border: `1px solid ${color}30`,
      borderRadius: 5,
      padding: '0.2rem 0.6rem',
      fontSize: '0.78rem',
      fontWeight: 600,
      whiteSpace: 'nowrap',
    }}>
      {children}
    </span>
  )
}

function HubCard({ to, icon, title, subtitle, description, badge }) {
  return (
    <Link to={to} style={{ textDecoration: 'none' }}>
      <div
        style={{
          background: '#fff',
          borderRadius: 10,
          border: '1px solid #e2e8f0',
          padding: '1.1rem',
          cursor: 'pointer',
          transition: 'box-shadow 0.15s, transform 0.15s',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
        }}
        onMouseEnter={e => {
          e.currentTarget.style.boxShadow = '0 4px 16px #0001'
          e.currentTarget.style.transform = 'translateY(-1px)'
        }}
        onMouseLeave={e => {
          e.currentTarget.style.boxShadow = 'none'
          e.currentTarget.style.transform = 'translateY(0)'
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem', gap: '0.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '1.3rem' }}>{icon}</span>
            <span style={{ fontWeight: 700, color: '#0f172a', fontSize: '1rem' }}>{title}</span>
          </div>
          {badge}
        </div>
        {subtitle && (
          <div style={{ fontSize: '0.72rem', color: '#94a3b8', marginBottom: '0.5rem', fontFamily: 'monospace' }}>
            {subtitle}
          </div>
        )}
        <p style={{ fontSize: '0.83rem', color: '#475569', lineHeight: 1.55, margin: 0, flexGrow: 1 }}>
          {description}
        </p>
      </div>
    </Link>
  )
}

function ResearchCard({ icon, title, subtitle, description }) {
  return (
    <div
      style={{
        background: '#fafaf9',
        borderRadius: 10,
        border: '1px dashed #d6d3d1',
        padding: '1.1rem',
        opacity: 0.85,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem', gap: '0.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '1.3rem' }}>{icon}</span>
          <span style={{ fontWeight: 700, color: '#78716c', fontSize: '1rem' }}>{title}</span>
        </div>
        <Badge color="#a8a29e">soon</Badge>
      </div>
      {subtitle && (
        <div style={{ fontSize: '0.72rem', color: '#a8a29e', marginBottom: '0.5rem', fontFamily: 'monospace' }}>
          {subtitle}
        </div>
      )}
      <p style={{ fontSize: '0.83rem', color: '#78716c', lineHeight: 1.55, margin: 0, flexGrow: 1 }}>
        {description}
      </p>
    </div>
  )
}

function timeAgo(isoStr, t) {
  if (!isoStr) return t('common.never')
  const diffMs = Date.now() - new Date(isoStr).getTime()
  const diffH = Math.floor(diffMs / 3600000)
  const diffD = Math.floor(diffH / 24)
  if (diffD >= 1) return t('dashboardHub.daysAgo', { n: diffD })
  if (diffH >= 1) return t('dashboardHub.hoursAgo', { n: diffH })
  return t('dashboardHub.minutesAgo', { n: Math.max(1, Math.floor(diffMs / 60000)) })
}

export default function Dashboard() {
  const { t, i18n } = useTranslation()
  const pl = i18n.language === 'pl'

  // Fetch every data source in parallel; each is independent
  const { data: decision } = useQuery({ queryKey: ['hub-decision'], queryFn: () => fetch(`/decision?lang=${pl ? 'pl' : 'en'}`) })
  const { data: portfolio } = useQuery({ queryKey: ['hub-portfolio'], queryFn: () => fetch('/portfolio') })
  const { data: tickers } = useQuery({ queryKey: ['hub-tickers'], queryFn: () => fetch('/tickers') })
  const { data: situation } = useQuery({ queryKey: ['hub-situation'], queryFn: () => fetch('/situation') })
  const { data: mlSummary } = useQuery({ queryKey: ['hub-ml-summary'], queryFn: () => fetch('/ml/summary') })
  const { data: dashApi } = useQuery({ queryKey: ['hub-dashboard'], queryFn: () => fetch('/dashboard') })

  const asOf = dashApi?.as_of ?? mlSummary?.hmm?.date

  // Decision badge
  const decBadge = decision ? (
    <Badge color={ACTION_COLOR[decision.action] ?? '#6b7280'}>
      {decision.action ?? '—'}
    </Badge>
  ) : null

  // Portfolio badge
  const portBadge = portfolio ? (
    <Badge color="#475569">
      {(portfolio.total_value_pln ?? 0).toLocaleString(pl ? 'pl-PL' : 'en-US', { maximumFractionDigits: 0 })} PLN
    </Badge>
  ) : null

  // History badge
  const histBadge = tickers ? (
    <Badge color="#475569">{tickers.length} {t('dashboardHub.tickers')}</Badge>
  ) : null

  // Situation badge: time since last pulse
  const sitBadge = situation?.pulse?.created_at ? (
    <Badge color="#475569">{timeAgo(situation.pulse.created_at, t)}</Badge>
  ) : null

  // ML hub badge: current regime state
  const mlState = mlSummary?.hmm?.state
  const mlBadge = mlState ? (
    <Badge color={REGIME_COLORS[mlState] ?? '#6b7280'}>
      {mlState}
    </Badge>
  ) : null

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto', padding: '1.5rem 1rem' }}>
      {/* Welcome header */}
      <div style={{ marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#0f172a', marginBottom: '0.3rem' }}>
          {t('dashboardHub.welcome')}
        </h1>
        <p style={{ color: '#64748b', fontSize: '0.9rem', margin: 0 }}>
          {asOf
            ? t('dashboardHub.asOf', { date: asOf }) + ' · ' + t('dashboardHub.tagline')
            : t('dashboardHub.tagline')}
        </p>
      </div>

      {/* Verdict highlight — pulled from /decision */}
      {decision && (
        <Link to="/decision" style={{ textDecoration: 'none' }}>
          <div
            style={{
              background: '#fff',
              borderRadius: 12,
              border: '1px solid #e2e8f0',
              borderLeft: `5px solid ${ACTION_COLOR[decision.action] ?? '#6b7280'}`,
              padding: '1.2rem 1.4rem',
              marginBottom: '1.5rem',
              cursor: 'pointer',
              transition: 'box-shadow 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.boxShadow = '0 4px 16px #0001'}
            onMouseLeave={e => e.currentTarget.style.boxShadow = 'none'}
          >
            <div style={{ fontSize: '0.7rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.4rem' }}>
              {t('dashboardHub.thisMonthsRecommendation')}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
              <span style={{
                background: ACTION_COLOR[decision.action] ?? '#6b7280',
                color: '#fff',
                padding: '0.4rem 0.9rem',
                borderRadius: 6,
                fontWeight: 700,
                fontSize: '1.05rem',
                letterSpacing: '0.04em',
              }}>
                {decision.action}
              </span>
              <span style={{ color: '#475569', fontSize: '0.95rem', flex: 1, minWidth: 200 }}>
                {decision.reasons?.[0] ?? '—'}
              </span>
              <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                {t('dashboardHub.fullAnalysis')} →
              </span>
            </div>
          </div>
        </Link>
      )}

      {/* Card grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '1rem' }}>
        <HubCard
          to="/decision"
          icon="🎯"
          title={t('nav.decision')}
          subtitle={t('dashboardHub.decisionSubtitle')}
          description={t('dashboardHub.decisionDesc')}
          badge={decBadge}
        />
        <HubCard
          to="/portfolio"
          icon="📊"
          title={t('nav.portfolio')}
          subtitle={t('dashboardHub.portfolioSubtitle')}
          description={t('dashboardHub.portfolioDesc')}
          badge={portBadge}
        />
        <HubCard
          to="/history"
          icon="📈"
          title={t('nav.history')}
          subtitle={t('dashboardHub.historySubtitle')}
          description={t('dashboardHub.historyDesc')}
          badge={histBadge}
        />
        <HubCard
          to="/situation"
          icon="📰"
          title={t('nav.situation')}
          subtitle={t('dashboardHub.situationSubtitle')}
          description={t('dashboardHub.situationDesc')}
          badge={sitBadge}
        />
        <HubCard
          to="/ml"
          icon="🤖"
          title={t('nav.ml')}
          subtitle={t('dashboardHub.mlSubtitle')}
          description={t('dashboardHub.mlDesc')}
          badge={mlBadge}
        />
        <ResearchCard
          icon="⚠"
          title={t('dashboardHub.researchTitle')}
          subtitle={t('dashboardHub.researchSubtitle')}
          description={t('dashboardHub.researchDesc')}
        />
      </div>

      {/* Footer note */}
      <div style={{
        marginTop: '2rem',
        padding: '0.85rem 1.1rem',
        background: '#f8fafc',
        borderRadius: 8,
        border: '1px solid #e2e8f0',
        fontSize: '0.78rem',
        color: '#64748b',
        textAlign: 'center',
      }}>
        {t('dashboardHub.footer')}
      </div>
    </div>
  )
}
