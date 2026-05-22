import { useState, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import client from '../api/client'
import RegimeBar   from '../components/RegimeBar'
import VolGauge    from '../components/VolGauge'
import FXFanChart  from '../components/FXFanChart'
import SignalPanel from '../components/SignalPanel'

function fetchDecision(lang) {
  return client.get(`/decision?lang=${lang}`).then(r => r.data)
}
function fetchProjection(years, monthly) {
  return client.get(`/decision/projection?years=${years}&monthly_pln=${monthly}`).then(r => r.data)
}
function fetchDashboard() {
  return client.get('/dashboard').then(r => r.data)
}

const ACTION_COLOR = { INVEST: '#22c55e', DCA: '#f97316', WAIT: '#ef4444' }
const ACTION_ICON  = { INVEST: '✓', DCA: '~', WAIT: '✗' }
const REGIME_COLOR = {
  bull:          '#22c55e',
  consolidation: '#3b82f6',
  stagflation:   '#f97316',
  bear:          '#ef4444',
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

export default function Decision() {
  const { t, i18n } = useTranslation()
  const lang = i18n.language === 'pl' ? 'pl' : 'en'

  // Display values — update immediately on keystroke
  const [yearsInput,   setYearsInput]   = useState(20)
  const [monthlyInput, setMonthlyInput] = useState(500)

  // Debounced values — only update after user stops typing (600ms)
  const [years,   setYears]   = useState(20)
  const [monthly, setMonthly] = useState(500)
  const debounceRef = useRef(null)

  function handleYearsChange(val) {
    setYearsInput(val)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      const n = Math.max(1, Math.min(50, Number(val)))
      if (!isNaN(n) && n > 0) setYears(n)
    }, 600)
  }
  function handleMonthlyChange(val) {
    setMonthlyInput(val)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      const n = Math.max(0, Math.min(50000, Number(val)))
      if (!isNaN(n)) setMonthly(n)
    }, 600)
  }

  const { data: dec, isLoading: decLoading, error: decError } = useQuery({
    queryKey: ['decision', lang],
    queryFn:  () => fetchDecision(lang),
    retry: 1,
  })

  const { data: proj, isLoading: projLoading } = useQuery({
    queryKey: ['projection', years, monthly],
    queryFn:  () => fetchProjection(years, monthly),
  })

  const { data: dash } = useQuery({
    queryKey: ['decision-dashboard'],
    queryFn:  fetchDashboard,
    refetchInterval: 5 * 60 * 1000,
  })

  const [showDecDetail, setShowDecDetail] = useState(false)

  const regime = dash?.regime
  const regime_duration = dash?.regime_duration
  const correlation = dash?.correlation
  const volatility = dash?.volatility ?? []
  const fx = dash?.fx ?? []
  const macro = dash?.macro

  return (
    <div className="decision-page">
      {/* ── VERDICT CARD ───────────────────────────────────── */}
      <div className="card">
        <h2>{t('decision.title')}</h2>
        {decLoading ? <p>{t('decision.loading')}</p> : decError ? (
          <div className="error-box">
            <strong>{t('decision.loadFailed')}</strong>
            <p>{decError.response?.data?.detail ?? decError.message}</p>
            <p className="error-hint">{t('decision.mlHint')}</p>
          </div>
        ) : dec && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
              <div className="action-badge" style={{ background: ACTION_COLOR[dec.action] }}>
                {ACTION_ICON[dec.action]} {dec.action}
              </div>
              <span className="confidence-tag">{t('decision.confidence')}: {dec.confidence}</span>
            </div>

            <ul className="reasons">
              {dec.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>

            {dec.flags.length > 0 && (
              <div className="flags">
                <strong>{t('decision.flags')}:</strong>
                {dec.flags.map((f, i) => <p key={i} className="flag">{f}</p>)}
              </div>
            )}

            <button
              onClick={() => setShowDecDetail(d => !d)}
              style={{
                marginTop: '0.75rem', background: 'none', border: '1px solid #e2e8f0',
                borderRadius: 6, padding: '0.3rem 0.75rem', fontSize: '0.8rem',
                color: '#64748b', cursor: 'pointer',
              }}
            >
              {t('decision.showDetail')} {showDecDetail ? '▲' : '▼'}
            </button>

            {showDecDetail && (
              <div style={{ marginTop: '0.75rem' }}>
                <div className="signal-grid">
                  <div>
                    <span>{t('decision.hmmRegime')}</span>
                    <strong style={{ color: dec.signals.prob_stagflation > 0.5 ? '#f97316' : dec.signals.prob_bear > 0.35 ? '#ef4444' : '#22c55e' }}>
                      {dec.signals.prob_stagflation > 0.5 ? t('signals.stagflation')
                       : dec.signals.prob_bear > 0.35 ? t('signals.bear') : t('signals.bull')}
                    </strong>
                  </div>
                  <div>
                    <span>{t('decision.recessionProb')}</span>
                    <strong>{dec.signals.recession_prob != null ? (dec.signals.recession_prob * 100).toFixed(0) + '%' : '—'}</strong>
                  </div>
                  <div>
                    <span>{t('decision.vol21d')}</span>
                    <strong>{dec.signals.vol_21d_forecast != null ? (dec.signals.vol_21d_forecast * 100).toFixed(1) + '%' : '—'}</strong>
                  </div>
                  <div>
                    <span>{t('decision.usdplnNow')}</span>
                    <strong>{dec.signals.usdpln_current?.toFixed(4) ?? '—'}</strong>
                  </div>
                  <div>
                    <span>{t('decision.usdpln90th')}</span>
                    <strong>{dec.signals.usdpln_upper_21d?.toFixed(4) ?? '—'}</strong>
                  </div>
                  <div>
                    <span>{t('decision.cpiUs')}</span>
                    <strong>{dec.signals.cpi_us_yoy?.toFixed(1) ?? '—'}%</strong>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* ── PROJECTION CARD ─────────────────────────────────── */}
      <div className="card">
        <h2>{t('decision.projection')}</h2>
        <div className="proj-controls">
          <label>
            {t('decision.horizon')}
            <input type="number" min="1" max="50" value={yearsInput}
                   onChange={e => handleYearsChange(e.target.value)} />
          </label>
          <label>
            {t('decision.monthly')}
            <input type="number" min="0" max="50000" step="50" value={monthlyInput}
                   onChange={e => handleMonthlyChange(e.target.value)} />
          </label>
        </div>

        {projLoading ? <p>{t('decision.loadingProj')}</p> : proj && (
          <>
            <div className="ensemble-grid">
              {proj.ensemble.weights.cape === 0 ? (
                <div className="ensemble-item" style={{ opacity: 0.4 }}>
                  <span>{t('decision.capeSignal')}</span>
                  <strong>—</strong>
                  <small>{t('decision.capeNA')}</small>
                </div>
              ) : (
                <div className="ensemble-item">
                  <span>{t('decision.capeSignal')}</span>
                  <strong>{(proj.ensemble.cape_return * 100).toFixed(1)}%</strong>
                  <small>{t('decision.capeDecile', { decile: proj.ensemble.cape_decile, weight: (proj.ensemble.weights.cape * 100).toFixed(0) })}</small>
                </div>
              )}
              <div className="ensemble-item">
                <span>{t('decision.baseRate')}</span>
                <strong>{(proj.ensemble.base_rate_return * 100).toFixed(1)}%</strong>
                <small>{t('decision.baseRateNote', { weight: (proj.ensemble.weights.base_rate * 100).toFixed(0) })}</small>
              </div>
              {proj.ensemble.weights.momentum === 0 ? (
                <div className="ensemble-item" style={{ opacity: 0.4 }}>
                  <span>{t('decision.momentum')}</span>
                  <strong>—</strong>
                  <small>{t('decision.momentumNA')}</small>
                </div>
              ) : (
                <div className="ensemble-item">
                  <span>{t('decision.momentum')}</span>
                  <strong>{(proj.ensemble.momentum_return * 100).toFixed(1)}%</strong>
                  <small>{t('decision.momentumNote', { adj: (proj.ensemble.momentum_adj >= 0 ? '+' : '') + (proj.ensemble.momentum_adj * 100).toFixed(2), weight: (proj.ensemble.weights.momentum * 100).toFixed(0) })}</small>
                </div>
              )}
              <div className="ensemble-item ensemble-result">
                <span>{t('decision.ensembleMedian')}</span>
                <strong>{(proj.ensemble.ensemble_median * 100).toFixed(1)}%</strong>
                <small>± {(proj.ensemble.ensemble_std * 100).toFixed(1)}% std · {t('decision.currentPortfolio', { value: proj.current_value_pln.toLocaleString('pl-PL', { maximumFractionDigits: 0 }) })}</small>
              </div>
            </div>

            <p className="proj-horizon-note">{t('decision.horizonNote')}</p>

            <ResponsiveContainer width="100%" height={320}>
              <AreaChart data={proj.paths} margin={{ top: 10, right: 20, left: 20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="year" label={{ value: t('decision.year'), position: 'insideBottom', offset: -4 }} />
                <YAxis tickFormatter={v => `${(v / 1000).toFixed(0)}k`}
                       label={{ value: t('decision.pln'), angle: -90, position: 'insideLeft' }} />
                <Tooltip formatter={(v) => `${v.toLocaleString('pl-PL', { maximumFractionDigits: 0 })} PLN`} />
                <Legend />
                <Area type="monotone" dataKey="p90_pln" name={t('decision.p90label')}
                      stroke="#93c5fd" fill="#dbeafe" strokeWidth={1} />
                <Area type="monotone" dataKey="median_pln" name={t('decision.medianLabel')}
                      stroke="#3b82f6" fill="#bfdbfe" strokeWidth={2} />
                <Area type="monotone" dataKey="p10_pln" name={t('decision.p10label')}
                      stroke="#1d4ed8" fill="#93c5fd" strokeWidth={1} />
              </AreaChart>
            </ResponsiveContainer>

            <p className="proj-disclaimer">{t('decision.disclaimer')}</p>
            <p className="proj-disclaimer" style={{ marginTop: '0.5rem', borderTop: '1px solid #e2e8f0', paddingTop: '0.5rem' }}>
              {t('decision.disclaimerEarnings')}
            </p>
          </>
        )}
      </div>

      {/* ── SUPPORTING SIGNALS ──────────────────────────────── */}
      {dash && (
        <>
          <div style={{
            marginTop: '1.5rem', marginBottom: '0.75rem',
            padding: '0.85rem 1.1rem',
            background: '#f8fafc',
            borderRadius: 8,
            border: '1px solid #e2e8f0',
          }}>
            <h3 style={{ margin: 0, color: '#0f172a', fontSize: '1.05rem' }}>
              {t('decision.supportingSignals')}
            </h3>
            <p style={{ margin: '0.35rem 0 0', color: '#64748b', fontSize: '0.82rem' }}>
              {t('decision.supportingSignalsDesc')}
            </p>
          </div>

          <CollapsibleSection
            title={t('dashboard.multiModel')}
            defaultOpen={true}
            infoText={t('dashboard.infoSignalPanel')}
          >
            <SignalPanel />
          </CollapsibleSection>

          {regime && (
            <CollapsibleSection
              title={t('dashboard.regime')}
              defaultOpen={false}
              infoText={t('dashboard.infoRegime')}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.5rem' }}>
                <div className="regime-label" style={{ color: REGIME_COLOR[regime.state] ?? '#6b7280', fontSize: '1.3rem', fontWeight: 700 }}>
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
          )}

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

          {volatility.length > 0 && (
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
          )}

          {fx.length > 0 && macro?.usdpln && (
            <CollapsibleSection
              title={t('dashboard.usdplnForecast')}
              defaultOpen={false}
              infoText={t('dashboard.infoFX')}
            >
              <FXFanChart signals={fx} current={macro.usdpln} />
            </CollapsibleSection>
          )}

          {macro && (
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
          )}
        </>
      )}
    </div>
  )
}
