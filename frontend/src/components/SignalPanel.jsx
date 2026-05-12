import { useQuery } from '@tanstack/react-query'
import client from '../api/client'

function fetchSignals() {
  return client.get('/signals').then(r => r.data)
}

const AGREEMENT_COLOR = { BULLISH: '#22c55e', BEARISH: '#ef4444', MIXED: '#f97316', UNKNOWN: '#6b7280' }
const AGREEMENT_ICON  = { BULLISH: '↑', BEARISH: '↓', MIXED: '~', UNKNOWN: '?' }

const HMM_COLOR = { bull: '#22c55e', consolidation: '#3b82f6', stagflation: '#f97316', bear: '#ef4444' }
const LGBM_COLOR = { risk_on: '#22c55e', risk_off: '#ef4444', stagflation: '#f97316', deflation: '#a855f7' }

function SignalCard({ title, subtitle, color, children, note }) {
  return (
    <div className="signal-card" style={{ borderTop: `3px solid ${color}` }}>
      <div className="signal-card-header">
        <span className="signal-card-title">{title}</span>
        <span className="signal-card-sub">{subtitle}</span>
      </div>
      <div className="signal-card-body">{children}</div>
      {note && <div className="signal-card-note">{note}</div>}
    </div>
  )
}

function ProbBar({ label, value, color }) {
  if (value == null) return null
  const pct = (value * 100).toFixed(1)
  return (
    <div className="prob-bar-row">
      <span className="prob-bar-label">{label}</span>
      <div className="prob-bar-track">
        <div className="prob-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="prob-bar-value">{pct}%</span>
    </div>
  )
}

export default function SignalPanel() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['signals'],
    queryFn:  fetchSignals,
    refetchInterval: 5 * 60 * 1000,
  })

  if (isLoading) return <p className="loading">Loading signal panel...</p>
  if (error)     return <p className="error">Failed to load signals: {error.message}</p>
  if (!data)     return null

  const { lgbm_regime: lgbm, hmm_regime: hmm, recession, cape_10y: cape,
          signal_agreement: agreement, bearish_count, total_signals } = data

  const agColor = AGREEMENT_COLOR[agreement] ?? '#6b7280'

  return (
    <div className="signal-panel">
      {/* Agreement header */}
      <div className="signal-agreement" style={{ borderColor: agColor }}>
        <span className="signal-agreement-icon" style={{ color: agColor }}>
          {AGREEMENT_ICON[agreement]}
        </span>
        <div>
          <span className="signal-agreement-label" style={{ color: agColor }}>
            {agreement}
          </span>
          <span className="signal-agreement-sub">
            {bearish_count}/{total_signals} signals bearish · as of {data.as_of}
          </span>
        </div>
      </div>

      <div className="signal-cards">
        {/* LightGBM */}
        {lgbm && (
          <SignalCard
            title="LightGBM Regime"
            subtitle={lgbm.date}
            color={LGBM_COLOR[lgbm.regime] ?? '#6b7280'}
            note={lgbm.note}
          >
            <div className="signal-main-label" style={{ color: LGBM_COLOR[lgbm.regime] }}>
              {lgbm.regime.replace('_', ' ').toUpperCase()}
            </div>
            <ProbBar label="Risk-on"     value={lgbm.prob_risk_on}     color="#22c55e" />
            <ProbBar label="Stagflation" value={lgbm.prob_stagflation} color="#f97316" />
            <ProbBar label="Risk-off"    value={lgbm.prob_risk_off}    color="#ef4444" />
            <ProbBar label="Deflation"   value={lgbm.prob_deflation}   color="#a855f7" />
          </SignalCard>
        )}

        {/* HMM */}
        {hmm && (
          <SignalCard
            title="HMM Regime"
            subtitle={hmm.date}
            color={HMM_COLOR[hmm.state] ?? '#6b7280'}
            note={hmm.note}
          >
            <div className="signal-main-label" style={{ color: HMM_COLOR[hmm.state] }}>
              {hmm.state.toUpperCase()}
            </div>
            <ProbBar label="Bull"          value={hmm.prob_bull}          color="#22c55e" />
            <ProbBar label="Consolidation" value={hmm.prob_consolidation} color="#3b82f6" />
            <ProbBar label="Bear"          value={hmm.prob_bear}          color="#ef4444" />
          </SignalCard>
        )}

        {/* Recession */}
        {recession && (
          <SignalCard
            title="Recession Risk"
            subtitle={recession.date}
            color={recession.recession_prob > 0.5 ? '#ef4444' : recession.recession_prob > 0.25 ? '#f97316' : '#22c55e'}
            note={recession.note}
          >
            <div className="signal-main-label"
                 style={{ color: recession.recession_prob > 0.5 ? '#ef4444' : recession.recession_prob > 0.25 ? '#f97316' : '#22c55e' }}>
              {(recession.recession_prob * 100).toFixed(1)}%
            </div>
            <ProbBar label="Recession prob" value={recession.recession_prob}
                     color={recession.recession_prob > 0.3 ? '#ef4444' : '#22c55e'} />
          </SignalCard>
        )}

        {/* CAPE */}
        {cape && (
          <SignalCard
            title="CAPE 10Y Outlook"
            subtitle={`CAPE = ${cape.cape} · ${cape.date}`}
            color={cape.ret_q50 < 0.02 ? '#ef4444' : cape.ret_q50 < 0.05 ? '#f97316' : '#22c55e'}
            note={cape.note}
          >
            <div className="signal-main-label"
                 style={{ color: cape.ret_q50 < 0.02 ? '#ef4444' : cape.ret_q50 < 0.05 ? '#f97316' : '#22c55e' }}>
              {(cape.ret_q50 * 100).toFixed(1)}% real
            </div>
            <div className="cape-band">
              <div className="cape-band-row">
                <span>10th pct</span><strong>{(cape.ret_q10 * 100).toFixed(1)}%</strong>
              </div>
              <div className="cape-band-row">
                <span>Median</span><strong>{(cape.ret_q50 * 100).toFixed(1)}%</strong>
              </div>
              <div className="cape-band-row">
                <span>90th pct</span><strong>{(cape.ret_q90 * 100).toFixed(1)}%</strong>
              </div>
            </div>
          </SignalCard>
        )}
      </div>
    </div>
  )
}
