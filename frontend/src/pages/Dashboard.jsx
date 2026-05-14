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
  risk_on:     '#22c55e',
  risk_off:    '#ef4444',
  stagflation: '#f97316',
  deflation:   '#a855f7',
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

  const { as_of, regime, volatility, fx, macro } = data
  const regimeColor = REGIME_COLOR[regime.regime] ?? '#6b7280'

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <h2>{t('dashboard.title')}</h2>
        <span className="as-of">{t('common.asOf')} {as_of}</span>
      </div>

      <div className="card">
        <h3>{t('dashboard.multiModel')}</h3>
        <SignalPanel />
      </div>

      <div className="card regime-card" style={{ borderLeft: `4px solid ${regimeColor}` }}>
        <h3>{t('dashboard.regime')}</h3>
        <div className="regime-label" style={{ color: regimeColor }}>
          {regime.regime.replace('_', ' ').toUpperCase()}
        </div>
        <RegimeBar
          probRiskOn     = {regime.prob_risk_on}
          probRiskOff    = {regime.prob_risk_off}
          probStagflation= {regime.prob_stagflation}
          probDeflation  = {regime.prob_deflation}
        />
        <p className="model-tag">{t('dashboard.model')}: {regime.model_version}</p>
      </div>

      <div className="card macro-card">
        <h3>{t('dashboard.macro')}</h3>
        <div className="macro-sections">
          <div className="macro-group">
            <div className="macro-group-title">{t('dashboard.riskSentiment')}</div>
            <table className="macro-table">
              <tbody>
                <tr>
                  <td>{t('dashboard.vix')}</td>
                  <td style={{ color: macro.vix_close > 30 ? '#ef4444' : macro.vix_close > 20 ? '#f97316' : '#22c55e' }}>
                    {macro.vix_close?.toFixed(1) ?? '—'}
                  </td>
                  <td className="macro-hint">{macro.vix_close > 30 ? t('dashboard.fear') : macro.vix_close > 20 ? t('dashboard.elevated') : t('dashboard.calm')}</td>
                </tr>
                <tr>
                  <td>{t('dashboard.hySpread')}</td>
                  <td style={{ color: macro.hy_spread > 600 ? '#ef4444' : macro.hy_spread > 400 ? '#f97316' : '#22c55e' }}>
                    {macro.hy_spread?.toFixed(0) ?? '—'} bps
                  </td>
                  <td className="macro-hint">{macro.hy_spread > 600 ? t('dashboard.stress') : macro.hy_spread > 400 ? t('dashboard.elevated') : t('dashboard.normal')}</td>
                </tr>
                <tr>
                  <td>{t('dashboard.acwi21d')}</td>
                  <td style={{ color: macro.acwi_ret_21d < -0.05 ? '#ef4444' : macro.acwi_ret_21d > 0.03 ? '#22c55e' : '#6b7280' }}>
                    {macro.acwi_ret_21d != null ? (macro.acwi_ret_21d * 100).toFixed(1) + '%' : '—'}
                  </td>
                  <td className="macro-hint"></td>
                </tr>
                <tr>
                  <td>{t('dashboard.acwi63d')}</td>
                  <td style={{ color: macro.acwi_ret_63d < -0.08 ? '#ef4444' : macro.acwi_ret_63d > 0.05 ? '#22c55e' : '#6b7280' }}>
                    {macro.acwi_ret_63d != null ? (macro.acwi_ret_63d * 100).toFixed(1) + '%' : '—'}
                  </td>
                  <td className="macro-hint"></td>
                </tr>
                <tr>
                  <td>{t('dashboard.wig20')}</td>
                  <td style={{ color: macro.wig20_ret_1d < -0.02 ? '#ef4444' : macro.wig20_ret_1d > 0.01 ? '#22c55e' : '#6b7280' }}>
                    {macro.wig20_ret_1d != null ? (macro.wig20_ret_1d * 100).toFixed(2) + '%' : '—'}
                  </td>
                  <td className="macro-hint"></td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="macro-group">
            <div className="macro-group-title">{t('dashboard.ratesYield')}</div>
            <table className="macro-table">
              <tbody>
                <tr><td>{t('dashboard.fedFunds')}</td><td>{macro.fed_funds_rate?.toFixed(2) ?? '—'}%</td><td className="macro-hint"></td></tr>
                <tr><td>{t('dashboard.ecbRate')}</td><td>{macro.ecb_rate?.toFixed(2) ?? '—'}%</td><td className="macro-hint"></td></tr>
                <tr><td>{t('dashboard.nbpRate')}</td><td>{macro.nbp_rate?.toFixed(2) ?? '—'}%</td><td className="macro-hint"></td></tr>
                <tr>
                  <td>{t('dashboard.spread10y3m')}</td>
                  <td style={{ color: macro.spread_10y_3m < 0 ? '#ef4444' : '#22c55e' }}>
                    {macro.spread_10y_3m?.toFixed(2) ?? '—'}%
                  </td>
                  <td className="macro-hint">{macro.yield_curve_inverted ? t('dashboard.inverted') : t('dashboard.normal')}</td>
                </tr>
                <tr>
                  <td>{t('dashboard.spread10y2y')}</td>
                  <td style={{ color: macro.spread_10y_2y < 0 ? '#ef4444' : '#22c55e' }}>
                    {macro.spread_10y_2y?.toFixed(2) ?? '—'}%
                  </td>
                  <td className="macro-hint">{macro.spread_10y_2y < 0 ? t('dashboard.inverted') : ''}</td>
                </tr>
                <tr><td>{t('dashboard.spEarnings')}</td><td>{macro.sp500_earnings_yield != null ? (macro.sp500_earnings_yield * 100).toFixed(2) + '%' : '—'}</td><td className="macro-hint"></td></tr>
              </tbody>
            </table>
          </div>

          <div className="macro-group">
            <div className="macro-group-title">{t('dashboard.inflation')}</div>
            <table className="macro-table">
              <tbody>
                <tr>
                  <td>{t('dashboard.usCpi')}</td>
                  <td style={{ color: macro.cpi_us_yoy > 4 ? '#ef4444' : macro.cpi_us_yoy > 2.5 ? '#f97316' : '#22c55e' }}>
                    {macro.cpi_us_yoy?.toFixed(1) ?? '—'}%
                  </td>
                  <td className="macro-hint">{macro.cpi_us_yoy > 4 ? t('dashboard.high') : macro.cpi_us_yoy > 2.5 ? t('dashboard.aboveTarget') : t('dashboard.onTarget')}</td>
                </tr>
                <tr>
                  <td>{t('dashboard.usCoreCpi')}</td>
                  <td style={{ color: macro.cpi_core_us_yoy > 4 ? '#ef4444' : macro.cpi_core_us_yoy > 2.5 ? '#f97316' : '#22c55e' }}>
                    {macro.cpi_core_us_yoy?.toFixed(1) ?? '—'}%
                  </td>
                  <td className="macro-hint"></td>
                </tr>
                <tr>
                  <td>{t('dashboard.eaCpi')}</td>
                  <td style={{ color: macro.cpi_ea_yoy > 4 ? '#ef4444' : macro.cpi_ea_yoy > 2.5 ? '#f97316' : '#22c55e' }}>
                    {macro.cpi_ea_yoy?.toFixed(1) ?? '—'}%
                  </td>
                  <td className="macro-hint"></td>
                </tr>
                <tr>
                  <td>{t('dashboard.plCpi')}</td>
                  <td style={{ color: macro.cpi_pl_yoy > 5 ? '#ef4444' : macro.cpi_pl_yoy > 2.5 ? '#f97316' : '#22c55e' }}>
                    {macro.cpi_pl_yoy?.toFixed(1) ?? '—'}%
                  </td>
                  <td className="macro-hint"></td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="macro-group">
            <div className="macro-group-title">{t('dashboard.fx')}</div>
            <table className="macro-table">
              <tbody>
                <tr><td>USD/PLN</td><td>{macro.usdpln?.toFixed(4) ?? '—'}</td><td className="macro-hint"></td></tr>
                <tr><td>EUR/PLN</td><td>{macro.eurpln?.toFixed(4) ?? '—'}</td><td className="macro-hint"></td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="card">
        <h3>{t('dashboard.volForecast')}</h3>
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
      </div>

      <div className="card">
        <h3>{t('dashboard.usdplnForecast')}</h3>
        <FXFanChart signals={fx} current={macro.usdpln} />
      </div>
    </div>
  )
}
