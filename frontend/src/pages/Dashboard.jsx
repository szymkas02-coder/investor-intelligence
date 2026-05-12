import { useQuery } from '@tanstack/react-query'
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
  const { data, isLoading, error } = useQuery({
    queryKey: ['dashboard'],
    queryFn:  fetchDashboard,
    refetchInterval: 5 * 60 * 1000,
  })

  if (isLoading) return <p className="loading">Loading dashboard...</p>
  if (error)     return <p className="error">Failed to load: {error.message}</p>

  const { as_of, regime, volatility, fx, macro } = data
  const regimeColor = REGIME_COLOR[regime.regime] ?? '#6b7280'

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <h2>Market Signal Panel</h2>
        <span className="as-of">as of {as_of}</span>
      </div>

      {/* Multi-model signal panel — key output, shown first */}
      <div className="card">
        <h3>Multi-Model Signal Panel</h3>
        <SignalPanel />
      </div>

      {/* Regime card */}
      <div className="card regime-card" style={{ borderLeft: `4px solid ${regimeColor}` }}>
        <h3>Current Regime — LightGBM</h3>
        <div className="regime-label" style={{ color: regimeColor }}>
          {regime.regime.replace('_', ' ').toUpperCase()}
        </div>
        <RegimeBar
          probRiskOn     = {regime.prob_risk_on}
          probRiskOff    = {regime.prob_risk_off}
          probStagflation= {regime.prob_stagflation}
          probDeflation  = {regime.prob_deflation}
        />
        <p className="model-tag">model: {regime.model_version}</p>
      </div>

      {/* Macro snapshot */}
      <div className="card macro-card">
        <h3>Macro Snapshot</h3>

        <div className="macro-sections">
          {/* Risk sentiment */}
          <div className="macro-group">
            <div className="macro-group-title">Risk Sentiment</div>
            <table className="macro-table">
              <tbody>
                <tr>
                  <td>VIX</td>
                  <td style={{ color: macro.vix_close > 30 ? '#ef4444' : macro.vix_close > 20 ? '#f97316' : '#22c55e' }}>
                    {macro.vix_close?.toFixed(1) ?? '—'}
                  </td>
                  <td className="macro-hint">{macro.vix_close > 30 ? 'fear' : macro.vix_close > 20 ? 'elevated' : 'calm'}</td>
                </tr>
                <tr>
                  <td>HY spread</td>
                  <td style={{ color: macro.hy_spread > 600 ? '#ef4444' : macro.hy_spread > 400 ? '#f97316' : '#22c55e' }}>
                    {macro.hy_spread?.toFixed(0) ?? '—'} bps
                  </td>
                  <td className="macro-hint">{macro.hy_spread > 600 ? 'stress' : macro.hy_spread > 400 ? 'elevated' : 'normal'}</td>
                </tr>
                <tr>
                  <td>ACWI 21d ret</td>
                  <td style={{ color: macro.acwi_ret_21d < -0.05 ? '#ef4444' : macro.acwi_ret_21d > 0.03 ? '#22c55e' : '#6b7280' }}>
                    {macro.acwi_ret_21d != null ? (macro.acwi_ret_21d * 100).toFixed(1) + '%' : '—'}
                  </td>
                  <td className="macro-hint"></td>
                </tr>
                <tr>
                  <td>ACWI 63d ret</td>
                  <td style={{ color: macro.acwi_ret_63d < -0.08 ? '#ef4444' : macro.acwi_ret_63d > 0.05 ? '#22c55e' : '#6b7280' }}>
                    {macro.acwi_ret_63d != null ? (macro.acwi_ret_63d * 100).toFixed(1) + '%' : '—'}
                  </td>
                  <td className="macro-hint"></td>
                </tr>
                <tr>
                  <td>WIG20 1d ret</td>
                  <td style={{ color: macro.wig20_ret_1d < -0.02 ? '#ef4444' : macro.wig20_ret_1d > 0.01 ? '#22c55e' : '#6b7280' }}>
                    {macro.wig20_ret_1d != null ? (macro.wig20_ret_1d * 100).toFixed(2) + '%' : '—'}
                  </td>
                  <td className="macro-hint"></td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Rates & yield curve */}
          <div className="macro-group">
            <div className="macro-group-title">Rates &amp; Yield Curve</div>
            <table className="macro-table">
              <tbody>
                <tr>
                  <td>Fed Funds</td>
                  <td>{macro.fed_funds_rate?.toFixed(2) ?? '—'}%</td>
                  <td className="macro-hint"></td>
                </tr>
                <tr>
                  <td>ECB rate</td>
                  <td>{macro.ecb_rate?.toFixed(2) ?? '—'}%</td>
                  <td className="macro-hint"></td>
                </tr>
                <tr>
                  <td>NBP rate</td>
                  <td>{macro.nbp_rate?.toFixed(2) ?? '—'}%</td>
                  <td className="macro-hint"></td>
                </tr>
                <tr>
                  <td>10Y–3M spread</td>
                  <td style={{ color: macro.spread_10y_3m < 0 ? '#ef4444' : '#22c55e' }}>
                    {macro.spread_10y_3m?.toFixed(2) ?? '—'}%
                  </td>
                  <td className="macro-hint">{macro.yield_curve_inverted ? '⚠ inverted' : 'normal'}</td>
                </tr>
                <tr>
                  <td>10Y–2Y spread</td>
                  <td style={{ color: macro.spread_10y_2y < 0 ? '#ef4444' : '#22c55e' }}>
                    {macro.spread_10y_2y?.toFixed(2) ?? '—'}%
                  </td>
                  <td className="macro-hint">{macro.spread_10y_2y < 0 ? '⚠ inverted' : ''}</td>
                </tr>
                <tr>
                  <td>S&amp;P earnings yield</td>
                  <td>{macro.sp500_earnings_yield != null ? (macro.sp500_earnings_yield * 100).toFixed(2) + '%' : '—'}</td>
                  <td className="macro-hint"></td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Inflation */}
          <div className="macro-group">
            <div className="macro-group-title">Inflation</div>
            <table className="macro-table">
              <tbody>
                <tr>
                  <td>US CPI YoY</td>
                  <td style={{ color: macro.cpi_us_yoy > 4 ? '#ef4444' : macro.cpi_us_yoy > 2.5 ? '#f97316' : '#22c55e' }}>
                    {macro.cpi_us_yoy?.toFixed(1) ?? '—'}%
                  </td>
                  <td className="macro-hint">{macro.cpi_us_yoy > 4 ? 'high' : macro.cpi_us_yoy > 2.5 ? 'above target' : 'on target'}</td>
                </tr>
                <tr>
                  <td>US Core CPI YoY</td>
                  <td style={{ color: macro.cpi_core_us_yoy > 4 ? '#ef4444' : macro.cpi_core_us_yoy > 2.5 ? '#f97316' : '#22c55e' }}>
                    {macro.cpi_core_us_yoy?.toFixed(1) ?? '—'}%
                  </td>
                  <td className="macro-hint"></td>
                </tr>
                <tr>
                  <td>EA CPI YoY</td>
                  <td style={{ color: macro.cpi_ea_yoy > 4 ? '#ef4444' : macro.cpi_ea_yoy > 2.5 ? '#f97316' : '#22c55e' }}>
                    {macro.cpi_ea_yoy?.toFixed(1) ?? '—'}%
                  </td>
                  <td className="macro-hint"></td>
                </tr>
                <tr>
                  <td>PL CPI YoY</td>
                  <td style={{ color: macro.cpi_pl_yoy > 5 ? '#ef4444' : macro.cpi_pl_yoy > 2.5 ? '#f97316' : '#22c55e' }}>
                    {macro.cpi_pl_yoy?.toFixed(1) ?? '—'}%
                  </td>
                  <td className="macro-hint"></td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* FX */}
          <div className="macro-group">
            <div className="macro-group-title">FX (PLN)</div>
            <table className="macro-table">
              <tbody>
                <tr>
                  <td>USD/PLN</td>
                  <td>{macro.usdpln?.toFixed(4) ?? '—'}</td>
                  <td className="macro-hint"></td>
                </tr>
                <tr>
                  <td>EUR/PLN</td>
                  <td>{macro.eurpln?.toFixed(4) ?? '—'}</td>
                  <td className="macro-hint"></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Volatility gauges */}
      <div className="card">
        <h3>Volatility Forecast (VWCE.DE)</h3>
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

      {/* FX fan chart */}
      <div className="card">
        <h3>USD/PLN Forecast</h3>
        <FXFanChart signals={fx} current={macro.usdpln} />
      </div>

    </div>
  )
}
