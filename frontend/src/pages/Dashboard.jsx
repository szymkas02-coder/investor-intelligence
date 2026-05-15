import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import client from '../api/client'
import RegimeBar   from '../components/RegimeBar'
import VolGauge    from '../components/VolGauge'
import FXFanChart  from '../components/FXFanChart'
import SignalPanel from '../components/SignalPanel'

function fetchDashboard() {
  return client.get('/dashboard').then(r => r.data)
}

const REGIME_COLOR = {
  bull:          '#22c55e',
  consolidation: '#3b82f6',
  stagflation:   '#f97316',
  bear:          '#ef4444',
}

// Derive a plain-language verdict from the dashboard data
function buildVerdict(regime, macro, cape, t) {
  const state = regime?.state
  const vix   = macro?.vix_close
  const cape_v = cape?.cape

  // Primary regime sentence
  let regimeSentence = ''
  if (state === 'stagflation') {
    regimeSentence = t('dashboard.verdictStagflation', { cape: cape_v?.toFixed(0) ?? '—' })
  } else if (state === 'bear') {
    regimeSentence = t('dashboard.verdictBear')
  } else if (state === 'bull') {
    regimeSentence = t('dashboard.verdictBull')
  } else {
    regimeSentence = t('dashboard.verdictConsolidation')
  }

  // Risk qualifier
  const riskPart = vix != null
    ? (vix > 25 ? t('dashboard.verdictVolHigh') : t('dashboard.verdictVolLow'))
    : ''

  return { regimeSentence, riskPart, color: REGIME_COLOR[state] ?? '#6b7280' }
}

function CollapsibleSection({ title, defaultOpen = false, children, infoText }) {
  const [open, setOpen]     = useState(defaultOpen)
  const [showInfo, setInfo] = useState(false)
  return (
    <div className="card collapsible-section">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}
           onClick={() => setOpen(o => !o)}>
        <h3 style={{ margin: 0 }}>{title}</h3>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          {infoText && (
            <span
              style={{ fontSize: '0.85rem', color: '#94a3b8', userSelect: 'none' }}
              onClick={e => { e.stopPropagation(); setInfo(i => !i) }}
              title="Co to znaczy?"
            >ⓘ</span>
          )}
          <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{open ? '▲' : '▼'}</span>
        </div>
      </div>
      {showInfo && infoText && (
        <div style={{
          marginTop: '0.75rem', padding: '0.75rem 1rem',
          background: '#f8fafc', borderLeft: '3px solid #3b82f6',
          borderRadius: '0 6px 6px 0', fontSize: '0.82rem',
          color: '#475569', lineHeight: 1.6,
        }}>
          {infoText}
        </div>
      )}
      {open && <div style={{ marginTop: '1rem' }}>{children}</div>}
    </div>
  )
}

export default function Dashboard() {
  const { t } = useTranslation()
  const { data, isLoading, error } = useQuery({
    queryKey: ['dashboard'],
    queryFn:  fetchDashboard,
    refetchInterval: 5 * 60 * 1000,
  })

  if (isLoading) return <p className="loading">{t('common.loading')}</p>
  if (error)     return <p className="error">{t('common.error')}: {error.message}</p>

  const { as_of, regime, regime_duration, correlation, volatility, fx, macro } = data

  // Fetch CAPE from signals for verdict (available via SignalPanel's /signals query,
  // but we approximate from dashboard macro: sp500_earnings_yield = 1/PE, not CAPE)
  // We use regime state + macro directly for the verdict
  const { regimeSentence, riskPart, color: verdictColor } = buildVerdict(regime, macro, null, t)

  const regimeColor = REGIME_COLOR[regime.state] ?? '#6b7280'
  const vol21 = volatility?.find(v => v.horizon_days === 21)

  return (
    <div className="dashboard">

      {/* ── VERDICT BANNER ── */}
      <div className="card verdict-banner" style={{ borderLeft: `5px solid ${verdictColor}` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              {t('dashboard.title')} · {t('common.asOf')} {as_of}
            </div>
            <p style={{ margin: '0 0 0.5rem', fontSize: '1.05rem', color: '#1e293b', lineHeight: 1.5 }}>
              <strong style={{ color: verdictColor }}>{regimeSentence}</strong>
              {riskPart && <span style={{ color: '#64748b' }}> {riskPart}</span>}
            </p>
          </div>
        </div>

        {/* 4 key numbers */}
        <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', marginTop: '0.75rem' }}>
          <KeyStat
            label={t('dashboard.vix')}
            value={macro.vix_close?.toFixed(0) ?? '—'}
            color={macro.vix_close > 30 ? '#ef4444' : macro.vix_close > 20 ? '#f97316' : '#22c55e'}
            hint={macro.vix_close > 30 ? t('dashboard.fear') : macro.vix_close > 20 ? t('dashboard.elevated') : t('dashboard.calm')}
          />
          <KeyStat
            label={t('dashboard.usCpi')}
            value={macro.cpi_us_yoy != null ? macro.cpi_us_yoy.toFixed(1) + '%' : '—'}
            color={macro.cpi_us_yoy > 4 ? '#ef4444' : macro.cpi_us_yoy > 2.5 ? '#f97316' : '#22c55e'}
            hint={macro.cpi_us_yoy > 4 ? t('dashboard.high') : macro.cpi_us_yoy > 2.5 ? t('dashboard.aboveTarget') : t('dashboard.onTarget')}
          />
          <KeyStat
            label={t('dashboard.acwi21d')}
            value={macro.acwi_ret_21d != null ? (macro.acwi_ret_21d * 100).toFixed(1) + '%' : '—'}
            color={macro.acwi_ret_21d < -0.05 ? '#ef4444' : macro.acwi_ret_21d > 0.03 ? '#22c55e' : '#6b7280'}
            hint=""
          />
          {vol21 && (
            <KeyStat
              label={t('dashboard.volForecastShort')}
              value={(vol21.vol_forecast * 100).toFixed(1) + '%'}
              color={vol21.vol_forecast > 0.30 ? '#ef4444' : vol21.vol_forecast > 0.20 ? '#f97316' : '#22c55e'}
              hint={t('dashboard.annualised')}
            />
          )}
          <KeyStat
            label="USD/PLN"
            value={macro.usdpln?.toFixed(4) ?? '—'}
            color="#6b7280"
            hint=""
          />
        </div>
      </div>

      {/* ── SIGNAL PANEL (collapsible) ── */}
      <CollapsibleSection
        title={t('dashboard.multiModel')}
        defaultOpen={true}
        infoText={t('dashboard.infoSignalPanel')}
      >
        <SignalPanel />
      </CollapsibleSection>

      {/* ── HMM REGIME (collapsible) ── */}
      <CollapsibleSection
        title={t('dashboard.regime')}
        defaultOpen={false}
        infoText={t('dashboard.infoRegime')}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.5rem' }}>
          <div className="regime-label" style={{ color: regimeColor, fontSize: '1.3rem', fontWeight: 700 }}>
            {t(`signals.${regime.state}`, regime.state).toUpperCase()}
          </div>
          <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{regime.model_version}</span>
        </div>
        <RegimeBar
          probBull          = {regime.prob_bull}
          probBear          = {regime.prob_bear}
          probConsolidation = {regime.prob_consolidation}
          probStagflation   = {regime.prob_stagflation}
        />
      </CollapsibleSection>

      {/* ── REGIME DURATION (collapsible) ── */}
      {regime_duration && (
        <CollapsibleSection
          title={t('dashboard.regimeDuration')}
          defaultOpen={false}
          infoText={t('dashboard.infoRegimeDuration')}
        >
          <p style={{ margin: '0 0 0.75rem', fontSize: '0.95rem', color: '#334155' }}>
            {t('dashboard.regimeDurationDetail', {
              months:   regime_duration.current_duration_months,
              state:    t(`signals.${regime_duration.current_state}`, regime_duration.current_state),
              survival: regime_duration.km_survival_at_current != null
                          ? (regime_duration.km_survival_at_current * 100).toFixed(0)
                          : '—',
              median:   regime_duration.median_duration ?? '—',
            })}
          </p>
          {regime_duration.median_duration && (
            <table className="macro-table">
              <tbody>
                <tr><td>{t('signals.durationP25')}</td><td><strong>{regime_duration.p25_duration ?? '—'}m</strong></td></tr>
                <tr><td>{t('signals.durationMedian')}</td><td><strong>{regime_duration.median_duration}m</strong></td></tr>
                <tr><td>{t('signals.durationP75')}</td><td><strong>{regime_duration.p75_duration ?? '—'}m</strong></td></tr>
              </tbody>
            </table>
          )}
        </CollapsibleSection>
      )}

      {/* ── DIVERSIFICATION (collapsible) ── */}
      {correlation && (
        <CollapsibleSection
          title={t('dashboard.marketStructure')}
          defaultOpen={false}
          infoText={t('dashboard.infoDiversification')}
        >
          <p style={{ margin: '0 0 0.75rem', fontSize: '0.95rem', color: '#334155' }}>
            {t('dashboard.divIndex', {
              value: correlation.diversification_index != null
                       ? (correlation.diversification_index * 100).toFixed(0)
                       : '—',
            })}
          </p>
          {correlation.top_correlations?.length > 0 && (
            <table className="macro-table">
              <tbody>
                {correlation.top_correlations.map(c => (
                  <tr key={c.pair}>
                    <td>{c.pair}</td>
                    <td style={{ color: c.r < -0.3 ? '#22c55e' : c.r > 0.7 ? '#ef4444' : '#6b7280', fontWeight: 600 }}>
                      {c.r > 0 ? '+' : ''}{c.r.toFixed(2)}
                    </td>
                    <td className="macro-hint" style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                      {c.r < -0.3 ? t('dashboard.corrNegGood') : c.r > 0.5 ? t('dashboard.corrHighWarn') : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CollapsibleSection>
      )}

      {/* ── MACRO SNAPSHOT (collapsible) ── */}
      <CollapsibleSection
        title={t('dashboard.macro')}
        defaultOpen={false}
        infoText={t('dashboard.infoMacro')}
      >
        <div className="macro-sections">
          <MacroGroup title={t('dashboard.riskSentiment')}>
            <MacroRow label={t('dashboard.vix')} value={macro.vix_close?.toFixed(1) ?? '—'}
              color={macro.vix_close > 30 ? '#ef4444' : macro.vix_close > 20 ? '#f97316' : '#22c55e'}
              hint={macro.vix_close > 30 ? t('dashboard.fear') : macro.vix_close > 20 ? t('dashboard.elevated') : t('dashboard.calm')} />
            <MacroRow label={t('dashboard.hySpread')} value={(macro.hy_spread?.toFixed(0) ?? '—') + ' bps'}
              color={macro.hy_spread > 600 ? '#ef4444' : macro.hy_spread > 400 ? '#f97316' : '#22c55e'}
              hint={macro.hy_spread > 600 ? t('dashboard.stress') : macro.hy_spread > 400 ? t('dashboard.elevated') : t('dashboard.normal')} />
            <MacroRow label={t('dashboard.acwi21d')}
              value={macro.acwi_ret_21d != null ? (macro.acwi_ret_21d * 100).toFixed(1) + '%' : '—'}
              color={macro.acwi_ret_21d < -0.05 ? '#ef4444' : macro.acwi_ret_21d > 0.03 ? '#22c55e' : '#6b7280'} />
            <MacroRow label={t('dashboard.acwi63d')}
              value={macro.acwi_ret_63d != null ? (macro.acwi_ret_63d * 100).toFixed(1) + '%' : '—'}
              color={macro.acwi_ret_63d < -0.08 ? '#ef4444' : macro.acwi_ret_63d > 0.05 ? '#22c55e' : '#6b7280'} />
            <MacroRow label={t('dashboard.wig20')}
              value={macro.wig20_ret_1d != null ? (macro.wig20_ret_1d * 100).toFixed(2) + '%' : '—'}
              color={macro.wig20_ret_1d < -0.02 ? '#ef4444' : macro.wig20_ret_1d > 0.01 ? '#22c55e' : '#6b7280'} />
          </MacroGroup>

          <MacroGroup title={t('dashboard.ratesYield')}>
            <MacroRow label={t('dashboard.fedFunds')} value={(macro.fed_funds_rate?.toFixed(2) ?? '—') + '%'} />
            <MacroRow label={t('dashboard.ecbRate')}  value={(macro.ecb_rate?.toFixed(2) ?? '—') + '%'} />
            <MacroRow label={t('dashboard.nbpRate')}  value={(macro.nbp_rate?.toFixed(2) ?? '—') + '%'} />
            <MacroRow label={t('dashboard.spread10y3m')}
              value={(macro.spread_10y_3m?.toFixed(2) ?? '—') + '%'}
              color={macro.spread_10y_3m < 0 ? '#ef4444' : '#22c55e'}
              hint={macro.yield_curve_inverted ? t('dashboard.inverted') : t('dashboard.normal')} />
            <MacroRow label={t('dashboard.spread10y2y')}
              value={(macro.spread_10y_2y?.toFixed(2) ?? '—') + '%'}
              color={macro.spread_10y_2y < 0 ? '#ef4444' : '#22c55e'}
              hint={macro.spread_10y_2y < 0 ? t('dashboard.inverted') : ''} />
            <MacroRow label={t('dashboard.spEarnings')}
              value={macro.sp500_earnings_yield != null ? (macro.sp500_earnings_yield * 100).toFixed(2) + '%' : '—'} />
          </MacroGroup>

          <MacroGroup title={t('dashboard.inflation')}>
            <MacroRow label={t('dashboard.usCpi')}     value={(macro.cpi_us_yoy?.toFixed(1) ?? '—') + '%'}
              color={macro.cpi_us_yoy > 4 ? '#ef4444' : macro.cpi_us_yoy > 2.5 ? '#f97316' : '#22c55e'}
              hint={macro.cpi_us_yoy > 4 ? t('dashboard.high') : macro.cpi_us_yoy > 2.5 ? t('dashboard.aboveTarget') : t('dashboard.onTarget')} />
            <MacroRow label={t('dashboard.usCoreCpi')} value={(macro.cpi_core_us_yoy?.toFixed(1) ?? '—') + '%'}
              color={macro.cpi_core_us_yoy > 4 ? '#ef4444' : macro.cpi_core_us_yoy > 2.5 ? '#f97316' : '#22c55e'} />
            <MacroRow label={t('dashboard.eaCpi')}     value={(macro.cpi_ea_yoy?.toFixed(1) ?? '—') + '%'}
              color={macro.cpi_ea_yoy > 4 ? '#ef4444' : macro.cpi_ea_yoy > 2.5 ? '#f97316' : '#22c55e'} />
            <MacroRow label={t('dashboard.plCpi')}     value={(macro.cpi_pl_yoy?.toFixed(1) ?? '—') + '%'}
              color={macro.cpi_pl_yoy > 5 ? '#ef4444' : macro.cpi_pl_yoy > 2.5 ? '#f97316' : '#22c55e'} />
          </MacroGroup>

          <MacroGroup title={t('dashboard.fx')}>
            <MacroRow label="USD/PLN" value={macro.usdpln?.toFixed(4) ?? '—'} />
            <MacroRow label="EUR/PLN" value={macro.eurpln?.toFixed(4) ?? '—'} />
          </MacroGroup>
        </div>
      </CollapsibleSection>

      {/* ── VOL FORECAST (collapsible) ── */}
      <CollapsibleSection
        title={t('dashboard.volForecast')}
        defaultOpen={false}
        infoText={t('dashboard.infoVol')}
      >
        <div className="vol-row">
          {volatility.map(v => (
            <VolGauge key={v.horizon_days}
              label    = {`${v.horizon_days}d`}
              forecast = {v.vol_forecast}
              lower    = {v.vol_lower}
              upper    = {v.vol_upper}
            />
          ))}
        </div>
      </CollapsibleSection>

      {/* ── FX FORECAST (collapsible) ── */}
      <CollapsibleSection
        title={t('dashboard.usdplnForecast')}
        defaultOpen={false}
        infoText={t('dashboard.infoFX')}
      >
        <FXFanChart signals={fx} current={macro.usdpln} />
      </CollapsibleSection>

    </div>
  )
}

function KeyStat({ label, value, color, hint }) {
  return (
    <div style={{ minWidth: 80 }}>
      <div style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</div>
      <div style={{ fontSize: '1.15rem', fontWeight: 700, color: color ?? '#1e293b' }}>{value}</div>
      {hint && <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>{hint}</div>}
    </div>
  )
}

function MacroGroup({ title, children }) {
  return (
    <div className="macro-group">
      <div className="macro-group-title">{title}</div>
      <table className="macro-table"><tbody>{children}</tbody></table>
    </div>
  )
}

function MacroRow({ label, value, color, hint }) {
  return (
    <tr>
      <td>{label}</td>
      <td style={color ? { color } : {}}>{value}</td>
      {hint !== undefined && <td className="macro-hint">{hint}</td>}
    </tr>
  )
}
