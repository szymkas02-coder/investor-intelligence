import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import client from '../api/client'

function fetchSignals() {
  return client.get('/signals').then(r => r.data)
}

const AGREEMENT_COLOR = { BULLISH: '#22c55e', BEARISH: '#ef4444', MIXED: '#f97316', UNKNOWN: '#6b7280' }
const AGREEMENT_ICON  = { BULLISH: '↑', BEARISH: '↓', MIXED: '~', UNKNOWN: '?' }
const HMM_COLOR = { bull: '#22c55e', consolidation: '#3b82f6', stagflation: '#f97316', bear: '#ef4444' }

function InfoBox({ text }) {
  return (
    <div style={{
      marginTop: '0.6rem', padding: '0.65rem 0.9rem',
      background: '#f8fafc', borderLeft: '3px solid #3b82f6',
      borderRadius: '0 6px 6px 0', fontSize: '0.8rem',
      color: '#475569', lineHeight: 1.65,
    }}>
      {text}
    </div>
  )
}

function SignalCard({ title, summary, summaryColor, detail, infoText }) {
  const [open, setOpen]     = useState(false)
  const [info, setInfo]     = useState(false)
  return (
    <div className="signal-card" style={{ borderTop: `3px solid ${summaryColor}` }}>
      {/* always-visible top: title + plain summary */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '0.2rem' }}>
            {title}
          </div>
          <div style={{ fontSize: '1.05rem', fontWeight: 700, color: summaryColor }}>
            {summary}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', paddingTop: '0.1rem' }}>
          {infoText && (
            <span style={{ fontSize: '0.8rem', color: '#94a3b8', cursor: 'pointer' }}
                  onClick={() => setInfo(i => !i)}
                  title="Co to znaczy?">ⓘ</span>
          )}
          {detail && (
            <span style={{ fontSize: '0.75rem', color: '#94a3b8', cursor: 'pointer' }}
                  onClick={() => setOpen(o => !o)}>
              {open ? '▲' : '▼'}
            </span>
          )}
        </div>
      </div>

      {info && infoText && <InfoBox text={infoText} />}
      {open && detail && <div style={{ marginTop: '0.75rem' }}>{detail}</div>}
    </div>
  )
}

function ValuationCard({ valuation: v, t }) {
  const trailingPe  = v.trailing_pe
  const usCape      = v.us_cape
  const globalCape  = v.global_cape
  const eps5y       = v.eps_growth_5y
  const epsHist     = v.eps_growth_hist_median
  const epsAbove    = eps5y != null && epsHist != null && eps5y > epsHist

  const capeColor = (c) => c > 30 ? '#ef4444' : c > 20 ? '#f97316' : '#22c55e'

  // Summary line: global CAPE + EPS growth direction
  const summary = globalCape != null
    ? t('signals.valuationSummary', {
        gcape: globalCape,
        dir: epsAbove ? t('signals.epsAboveShort') : t('signals.epsBelowShort'),
      })
    : '—'
  const summaryColor = globalCape > 28 ? '#ef4444' : globalCape > 22 ? '#f97316' : '#22c55e'

  return (
    <SignalCard
      title={t('signals.valuationTitle')}
      summary={summary}
      summaryColor={summaryColor}
      infoText={t('signals.infoValuation')}
      detail={
        <div className="cape-band">
          <div className="cape-band-row">
            <span>{t('signals.globalCape')}</span>
            <strong style={{ color: capeColor(globalCape) }}>{globalCape ?? '—'}</strong>
          </div>
          <div className="cape-band-row">
            <span>{t('signals.usCape')}</span>
            <strong style={{ color: capeColor(usCape) }}>{usCape ?? '—'}</strong>
          </div>
          <div className="cape-band-row">
            <span>{t('signals.trailingPe')}</span>
            <strong style={{ color: capeColor(trailingPe) }}>{trailingPe ?? '—'}</strong>
          </div>
          {eps5y != null && (
            <div className="cape-band-row">
              <span>{t('signals.eps5yCagr')}</span>
              <strong style={{ color: epsAbove ? '#22c55e' : '#f97316' }}>
                {(eps5y * 100).toFixed(1)}%
              </strong>
            </div>
          )}
          {epsHist != null && (
            <div className="cape-band-row">
              <span>{t('signals.epsHistMedian')}</span>
              <strong style={{ color: '#94a3b8' }}>{(epsHist * 100).toFixed(1)}%</strong>
            </div>
          )}
        </div>
      }
    />
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
  const { t } = useTranslation()
  const { data, isLoading, error } = useQuery({
    queryKey: ['signals'],
    queryFn:  fetchSignals,
    refetchInterval: 5 * 60 * 1000,
  })

  if (isLoading) return <p className="loading">{t('signals.loading')}</p>
  if (error)     return <p className="error">{t('signals.error')}: {error.message}</p>
  if (!data)     return null

  const { hmm_regime: hmm, recession, cape_10y: cape,
          regime_duration, valuation,
          signal_agreement: agreement,
          bearish_count, total_signals } = data

  const agColor = AGREEMENT_COLOR[agreement] ?? '#6b7280'

  // Plain-language HMM summary
  const hmmLabel = hmm ? t(`signals.${hmm.state}`, hmm.state) : '—'
  const hmmSummary = hmm
    ? t('signals.hmmSummary', { state: hmmLabel })
    : '—'

  // Plain-language recession summary
  const recProb = recession?.recession_prob ?? 0
  const recSummary = recProb < 0.1
    ? t('signals.recSummaryLow')
    : recProb < 0.3
    ? t('signals.recSummaryMid')
    : t('signals.recSummaryHigh')
  const recColor = recProb > 0.5 ? '#ef4444' : recProb > 0.25 ? '#f97316' : '#22c55e'

  // Plain-language CAPE summary
  const capeRet = cape?.ret_q50
  const capeSummary = capeRet == null ? '—'
    : capeRet < 0.02 ? t('signals.capeSummaryLow', { ret: (capeRet * 100).toFixed(1) })
    : capeRet < 0.05 ? t('signals.capeSummaryMid', { ret: (capeRet * 100).toFixed(1) })
    : t('signals.capeSummaryHigh', { ret: (capeRet * 100).toFixed(1) })
  const capeColor = capeRet < 0.02 ? '#ef4444' : capeRet < 0.05 ? '#f97316' : '#22c55e'

  // Plain-language regime duration summary
  const rdMonths  = regime_duration?.current_duration_months
  const rdSurvival = regime_duration?.km_survival_at_current
  const rdState   = regime_duration ? t(`signals.${regime_duration.current_state}`, regime_duration.current_state) : ''
  const rdSummary = regime_duration
    ? t('signals.rdSummary', {
        state: rdState,
        months: rdMonths,
        survival: rdSurvival != null ? (rdSurvival * 100).toFixed(0) : '—',
      })
    : '—'
  const rdColor = HMM_COLOR[regime_duration?.current_state] ?? '#6b7280'

  return (
    <div className="signal-panel">
      {/* Overall verdict line */}
      <div className="signal-agreement" style={{ borderColor: agColor }}>
        <span className="signal-agreement-icon" style={{ color: agColor }}>
          {AGREEMENT_ICON[agreement]}
        </span>
        <div>
          <span className="signal-agreement-label" style={{ color: agColor }}>
            {t(`signals.agreement${agreement}`, agreement)}
          </span>
          <span className="signal-agreement-sub" style={{ marginLeft: '0.5rem', color: '#94a3b8', fontSize: '0.8rem' }}>
            {t('signals.bearishCount', { count: bearish_count, total: total_signals })} · {t('common.asOf')} {data.as_of}
          </span>
        </div>
      </div>

      <div className="signal-cards">

        {/* HMM Regime */}
        {hmm && (
          <SignalCard
            title={t('signals.hmmTitle')}
            summary={hmmSummary}
            summaryColor={HMM_COLOR[hmm.state] ?? '#6b7280'}
            infoText={t('signals.infoHmm')}
            detail={
              <>
                <ProbBar label={t('signals.bull')}          value={hmm.prob_bull}          color="#22c55e" />
                <ProbBar label={t('signals.consolidation')} value={hmm.prob_consolidation} color="#3b82f6" />
                <ProbBar label={t('signals.stagflation')}   value={hmm.prob_stagflation}   color="#f97316" />
                <ProbBar label={t('signals.bear')}          value={hmm.prob_bear}          color="#ef4444" />
              </>
            }
          />
        )}

        {/* Regime Duration */}
        {regime_duration && (
          <SignalCard
            title={t('signals.rdTitle')}
            summary={rdSummary}
            summaryColor={rdColor}
            infoText={t('signals.infoRd')}
            detail={
              <div className="cape-band">
                <div className="cape-band-row"><span>{t('signals.durationP25')}</span><strong>{regime_duration.p25_duration ?? '—'}m</strong></div>
                <div className="cape-band-row"><span>{t('signals.durationMedian')}</span><strong>{regime_duration.median_duration ?? '—'}m</strong></div>
                <div className="cape-band-row"><span>{t('signals.durationP75')}</span><strong>{regime_duration.p75_duration ?? '—'}m</strong></div>
              </div>
            }
          />
        )}

        {/* Recession */}
        {recession && (
          <SignalCard
            title={t('signals.recTitle')}
            summary={recSummary}
            summaryColor={recColor}
            infoText={t('signals.infoRecession')}
            detail={
              <ProbBar label={t('signals.recessionProb')} value={recession.recession_prob}
                       color={recession.recession_prob > 0.3 ? '#ef4444' : '#22c55e'} />
            }
          />
        )}

        {/* CAPE */}
        {cape && (
          <SignalCard
            title={t('signals.capeTitle')}
            summary={capeSummary}
            summaryColor={capeColor}
            infoText={t('signals.infoCape')}
            detail={
              <div className="cape-band">
                <div className="cape-band-row"><span>{t('signals.p10')}</span><strong>{(cape.ret_q10 * 100).toFixed(1)}%</strong></div>
                <div className="cape-band-row"><span>{t('signals.median')}</span><strong>{(cape.ret_q50 * 100).toFixed(1)}%</strong></div>
                <div className="cape-band-row"><span>{t('signals.p90')}</span><strong>{(cape.ret_q90 * 100).toFixed(1)}%</strong></div>
                <div style={{ marginTop: '0.4rem', fontSize: '0.75rem', color: '#94a3b8' }}>CAPE = {cape.cape}</div>
              </div>
            }
          />
        )}

        {/* Valuation context: trailing P/E vs CAPE + EPS growth */}
        {valuation && (
          <ValuationCard valuation={valuation} t={t} />
        )}

      </div>
    </div>
  )
}
