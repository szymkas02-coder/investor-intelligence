import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import client from '../api/client'

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, Cell,
} from 'recharts'

function fetchTickers() {
  return client.get('/tickers').then(r => r.data)
}
function fetchPortfolio() {
  return client.get('/portfolio').then(r => r.data)
}
function fetchIkeHistory() {
  return client.get('/portfolio/ike-history').then(r => r.data)
}
function fetchTransactions(filters) {
  const params = new URLSearchParams()
  if (filters.ticker)  params.set('ticker', filters.ticker)
  if (filters.type)    params.set('type',   filters.type)
  if (filters.year)    params.set('year',   filters.year)
  return client.get(`/portfolio/transactions?${params}`).then(r => r.data)
}
function postTransaction(tx)            { return client.post('/portfolio/transaction', tx).then(r => r.data) }
function deleteTransaction(id)          { return client.delete(`/portfolio/transaction/${id}`).then(r => r.data) }
function putTransaction({ id, ...tx })  { return client.put(`/portfolio/transaction/${id}`, tx).then(r => r.data) }
function fetchPrice(ticker, date)       { return client.get(`/portfolio/price/${ticker}`, { params: date ? { on_date: date } : {} }).then(r => r.data) }


const EMPTY_TX = {
  ticker: '', date: new Date().toISOString().slice(0, 10),
  type: 'buy', shares: '', price_pln: '', amount_pln: '', account_type: 'IKE', notes: '',
}

const TYPE_COLOR = { buy: '#22c55e', sell: '#ef4444', dividend: '#3b82f6' }
const TYPE_LABEL = { buy: 'Buy', sell: 'Sell', dividend: 'Div' }

function exportCSV(transactions) {
  const header = ['Date', 'Ticker', 'Type', 'Shares', 'Price (PLN)', 'Total (PLN)', 'Account', 'Notes']
  const rows = transactions.map(t => [
    t.date, t.ticker, t.type,
    t.shares, t.price_pln,
    (t.shares * t.price_pln).toFixed(2),
    t.account_type, t.notes ?? '',
  ])
  const csv = [header, ...rows].map(r => r.join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a'); a.href = url
  a.download = `transactions_${new Date().toISOString().slice(0,10)}.csv`
  a.click(); URL.revokeObjectURL(url)
}

export default function Portfolio() {
  const qc = useQueryClient()
  const { t } = useTranslation()
  const [form,      setForm]      = useState(EMPTY_TX)
  const [msg,       setMsg]       = useState('')
  const [editId,     setEditId]    = useState(null)
  const [showForm,   setShowForm]  = useState(false)
  const [filters,    setFilters]   = useState({ ticker: '', type: '', year: '' })
  const [confirmDel,    setConfirmDel]    = useState(null)
  const [confirmDelAll, setConfirmDelAll] = useState(0)  // 0=idle 1=first confirm 2=second confirm
  const [priceHint,    setPriceHint]    = useState(null)
  const [priceLoading, setPriceLoading] = useState(false)
  const priceDebounce = useRef(null)
  const [uploadMsg,      setUploadMsg]      = useState(null)
  const [uploading,      setUploading]      = useState(false)
  const uploadRef       = useRef(null)
  const brokerUploadRef = useRef(null)
  const [brokerParsing,   setBrokerParsing]   = useState(false)
  const [brokerPreview,   setBrokerPreview]   = useState(null)   // { preview, parse_errors, message }
  const [brokerSheets,    setBrokerSheets]    = useState(null)   // list of sheet names
  const [brokerFileCache, setBrokerFileCache] = useState(null)   // cached File object for sheet re-parse
  const [brokerConfirming, setBrokerConfirming] = useState(false)
  const [brokerMsg,       setBrokerMsg]       = useState(null)

  // Auto-fetch price when ticker is set and form is open
  useEffect(() => {
    if (!showForm || !form.ticker || form.ticker.length < 3) { setPriceHint(null); return }
    clearTimeout(priceDebounce.current)
    priceDebounce.current = setTimeout(() => {
      setPriceLoading(true)
      fetchPrice(form.ticker, form.date)
        .then(p => { setPriceHint(p); setPriceLoading(false) })
        .catch(() => { setPriceHint(null); setPriceLoading(false) })
    }, 600)
  }, [form.ticker, form.date, showForm])

  const { data, isLoading: posLoading } = useQuery({ queryKey: ['portfolio'], queryFn: fetchPortfolio })
  const { data: ikeHistory } = useQuery({ queryKey: ['ike-history'], queryFn: fetchIkeHistory })
  const { data: tickersData } = useQuery({ queryKey: ['tickers'], queryFn: fetchTickers, staleTime: 10 * 60 * 1000 })
  const availableTickers = tickersData ?? []
  const tickerNames = Object.fromEntries(availableTickers.map(t => [t.ticker, t.name || t.ticker]))
  const { data: txData, isLoading: txLoading } = useQuery({
    queryKey: ['transactions', filters],
    queryFn:  () => fetchTransactions(filters),
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['portfolio'] })
    qc.invalidateQueries({ queryKey: ['transactions'] })
  }

  const addMutation = useMutation({
    mutationFn: postTransaction,
    onSuccess: (res) => { setMsg(res.message); setForm(EMPTY_TX); setShowForm(false); invalidate() },
    onError:   (err) => setMsg(`Error: ${err.response?.data?.detail ?? err.message}`),
  })
  const editMutation = useMutation({
    mutationFn: putTransaction,
    onSuccess: (res) => { setMsg(res.message); setEditId(null); setForm(EMPTY_TX); invalidate() },
    onError:   (err) => setMsg(`Error: ${err.response?.data?.detail ?? err.message}`),
  })
  const delMutation = useMutation({
    mutationFn: deleteTransaction,
    onSuccess: (res) => { setMsg(res.message); setConfirmDel(null); invalidate() },
    onError:   (err) => setMsg(`Error: ${err.response?.data?.detail ?? err.message}`),
  })

  const delAllMutation = useMutation({
    mutationFn: () => client.delete('/portfolio/transactions/all').then(r => r.data),
    onSuccess: (res) => { setMsg(res.message); setConfirmDelAll(0); invalidate() },
    onError:   (err) => { setMsg(`Error: ${err.response?.data?.detail ?? err.message}`); setConfirmDelAll(0) },
  })

  function handleSubmit(e) {
    e.preventDefault(); setMsg('')
    let payload
    if (form.type === 'deposit') {
      payload = { date: form.date, type: form.type, account_type: form.account_type,
                  amount_pln: parseFloat(form.amount_pln), notes: form.notes || null }
    } else {
      payload = { ...form, shares: parseFloat(form.shares), price_pln: parseFloat(form.price_pln) }
    }
    if (editId) editMutation.mutate({ id: editId, ...payload })
    else        addMutation.mutate(payload)
  }

  function startEdit(tx) {
    setEditId(tx.transaction_id)
    setForm({
      ticker: tx.ticker, date: tx.date, type: tx.type,
      shares: tx.shares, price_pln: tx.price_pln,
      account_type: tx.account_type, notes: tx.notes ?? '',
    })
    setShowForm(true)
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })
  }

  function cancelEdit() { setEditId(null); setForm(EMPTY_TX); setShowForm(false) }

  function downloadTemplate() {
    client.get('/portfolio/template', { responseType: 'blob' }).then(res => {
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a'); a.href = url
      a.download = 'transactions_template.xlsx'
      a.click(); URL.revokeObjectURL(url)
    })
  }

  async function handleUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true); setUploadMsg(null)
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await client.post('/portfolio/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setUploadMsg({ type: 'success', text: res.data.message, errors: res.data.errors })
      invalidate()
    } catch (err) {
      setUploadMsg({ type: 'error', text: err.response?.data?.detail ?? err.message, errors: [] })
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  async function handleBrokerUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setBrokerParsing(true); setBrokerMsg(null); setBrokerPreview(null); setBrokerSheets(null)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await client.post('/portfolio/upload-broker', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      if (res.data.sheets?.length > 1) {
        // Multiple sheets — let user pick
        setBrokerSheets(res.data.sheets)
        setBrokerFileCache(file)
      } else if (res.data.sheets?.length === 1) {
        // Single sheet — auto-select and parse immediately
        await _parseBrokerSheet(file, res.data.sheets[0])
      } else {
        // CSV — already parsed
        setBrokerPreview(res.data)
      }
    } catch (err) {
      setBrokerMsg({ type: 'error', text: err.response?.data?.detail ?? err.message })
    } finally {
      setBrokerParsing(false)
      e.target.value = ''
    }
  }

  async function _parseBrokerSheet(file, sheetName) {
    setBrokerParsing(true); setBrokerMsg(null)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await client.post(`/portfolio/upload-broker?sheet_name=${encodeURIComponent(sheetName)}`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setBrokerPreview(res.data)
      setBrokerSheets(null)
      setBrokerFileCache(null)
    } catch (err) {
      setBrokerMsg({ type: 'error', text: err.response?.data?.detail ?? err.message })
    } finally {
      setBrokerParsing(false)
    }
  }

  async function handleBrokerConfirm() {
    if (!brokerPreview?.preview?.length) return
    setBrokerConfirming(true)
    try {
      const res = await client.post('/portfolio/upload-broker/confirm', {
        transactions: brokerPreview.preview,
      })
      setBrokerMsg({ type: 'success', text: res.data.message, errors: res.data.errors })
      setBrokerPreview(null)
      invalidate()
    } catch (err) {
      setBrokerMsg({ type: 'error', text: err.response?.data?.detail ?? err.message })
    } finally {
      setBrokerConfirming(false)
    }
  }

  const transactions = txData?.transactions ?? []
  const years = [...new Set(transactions.map(t => t.date.slice(0, 4)))].sort((a, b) => b - a)

  return (
    <div className="portfolio-page">

      {/* IKE status */}
      {data && (
        <div className="card ike-card">
          <h3>IKE {new Date().getFullYear()} Contributions</h3>
          <div className="ike-bar-wrap">
            <div className="ike-bar" style={{ width: data.ike_limit
              ? `${Math.min(100, (data.ike_contributed / data.ike_limit) * 100).toFixed(0)}%` : '0%' }} />
          </div>
          <p>
            <strong>{data.ike_contributed?.toLocaleString('pl-PL', { maximumFractionDigits: 0 }) ?? 0} PLN</strong>
            {data.ike_limit && <>
              {' '}contributed of {data.ike_limit.toLocaleString('pl-PL')} PLN limit
              &nbsp;(<strong>{data.ike_remaining?.toLocaleString('pl-PL', { maximumFractionDigits: 0 })} PLN remaining</strong>)
            </>}
          </p>
        </div>
      )}

      {/* IKE multi-year history */}
      {ikeHistory?.years?.length > 0 && (
        <div className="card">
          <h3>IKE Contribution History</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={ikeHistory.years} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="year" tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={v => `${(v/1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v, name) => [
                v.toLocaleString('pl-PL', { maximumFractionDigits: 0 }) + ' PLN', name
              ]} />
              <Legend />
              <Bar dataKey="limit" name="Annual limit" fill="#e2e8f0" radius={[3,3,0,0]} />
              <Bar dataKey="contributed" name="Contributed" radius={[3,3,0,0]}>
                {ikeHistory.years.map(y => (
                  <Cell key={y.year}
                        fill={y.pct >= 100 ? '#22c55e' : y.pct >= 50 ? '#3b82f6' : '#94a3b8'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p className="ike-history-note">
            Green = limit reached · Blue = over 50% · Grey = under 50%
          </p>
        </div>
      )}

      {/* Positions */}
      <div className="card">
        <h3>
          Positions
          {data && <span className="total-value">
            Total: {data.total_value_pln?.toLocaleString('pl-PL', { maximumFractionDigits: 0 }) ?? '—'} PLN
          </span>}
        </h3>
        {posLoading ? <p>{t('common.loading')}</p> :
         !data?.positions.length ? <p className="empty">{t('portfolio.noPositions')}</p> :
        <table className="positions-table">
          <thead>
            <tr>
              <th>Ticker</th><th>Account</th><th>Shares</th>
              <th>Avg cost</th><th>Current</th><th>Value</th><th>Gain</th>
            </tr>
          </thead>
          <tbody>
            {data.positions.map(p => (
              <tr key={`${p.ticker}-${p.account_type}`}>
                <td><strong>{p.ticker}</strong>{tickerNames[p.ticker] && tickerNames[p.ticker] !== p.ticker && <><br /><small style={{color:'#64748b',fontWeight:'normal'}}>{tickerNames[p.ticker]}</small></>}</td>
                <td><span className="account-badge">{p.account_type}</span></td>
                <td>{p.shares.toFixed(4)}</td>
                <td>{p.avg_cost_pln?.toFixed(2)} PLN</td>
                <td>{p.current_price?.toFixed(2) ?? '—'}</td>
                <td><strong>{p.value_pln?.toLocaleString('pl-PL', { maximumFractionDigits: 0 }) ?? '—'} PLN</strong></td>
                <td style={{ color: (p.gain_pct ?? 0) >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                  {p.gain_pct != null ? `${(p.gain_pct * 100).toFixed(1)}%` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>}
      </div>

      {/* Transaction history */}
      <div className="card">
        <div className="tx-history-header">
          <h3>Transaction History
            <span className="tx-count">{transactions.length} records</span>
          </h3>
          <div className="tx-actions">
            {transactions.length > 0 && (
              <button className="btn-ghost btn-sm" onClick={() => exportCSV(transactions)}>
                {t('portfolio.export')}
              </button>
            )}
            <button className="btn-ghost btn-sm" onClick={downloadTemplate}>
              {t('portfolio.downloadTemplate')}
            </button>
            <button className="btn-ghost btn-sm" onClick={() => uploadRef.current?.click()} disabled={uploading}>
              {uploading ? t('common.loading') : t('portfolio.importExcel')}
            </button>
            <input ref={uploadRef} type="file" accept=".xlsx" style={{ display: 'none' }} onChange={handleUpload} />
            <button className="btn-ghost btn-sm" onClick={() => brokerUploadRef.current?.click()} disabled={brokerParsing}>
              {brokerParsing ? t('common.loading') : t('portfolio.importBroker')}
            </button>
            <input ref={brokerUploadRef} type="file" accept=".xlsx,.csv" style={{ display: 'none' }} onChange={handleBrokerUpload} />
            <button className="btn-danger btn-sm" onClick={() => setConfirmDelAll(1)}
                    disabled={!transactions.length}>
              ✕ {t('portfolio.deleteAll')}
            </button>
            <button className="btn-primary btn-sm" onClick={() => { setShowForm(v => !v); setEditId(null); setForm(EMPTY_TX) }}>
              {showForm && !editId ? `✕ ${t('portfolio.cancel')}` : `+ ${t('portfolio.addTransaction')}`}
            </button>
          </div>
        </div>

        {/* Upload result */}
        {uploadMsg && (
          <div className={uploadMsg.type === 'success' ? 'upload-result-ok' : 'upload-result-err'}>
            <span>{uploadMsg.text}</span>
            {uploadMsg.errors?.length > 0 && (
              <ul className="upload-errors">
                {uploadMsg.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            )}
            <button className="btn-icon" onClick={() => setUploadMsg(null)}>✕</button>
          </div>
        )}

        {/* Broker import result banner */}
        {brokerMsg && (
          <div className={brokerMsg.type === 'success' ? 'upload-result-ok' : 'upload-result-err'}>
            <span>{brokerMsg.text}</span>
            {brokerMsg.errors?.length > 0 && (
              <ul className="upload-errors">{brokerMsg.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
            )}
            <button className="btn-icon" onClick={() => setBrokerMsg(null)}>✕</button>
          </div>
        )}

        {/* Sheet picker */}
        {brokerSheets && (
          <div style={{ background: '#f8fafc', border: '1px solid #cbd5e1', borderRadius: 8, padding: 16, marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <strong>File has {brokerSheets.length} sheets — select one to import:</strong>
              <button className="btn-icon" onClick={() => { setBrokerSheets(null); setBrokerFileCache(null) }}>✕</button>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {brokerSheets.map(s => (
                <button key={s} className="btn-ghost btn-sm" disabled={brokerParsing}
                        onClick={() => _parseBrokerSheet(brokerFileCache, s)}>
                  {brokerParsing ? 'Parsing...' : s}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Broker preview modal */}
        {brokerPreview && (
          <div style={{ background: '#f8fafc', border: '1px solid #cbd5e1', borderRadius: 8, padding: 16, marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <strong>AI parsed {brokerPreview.preview.length} transaction(s) — review before importing</strong>
              <button className="btn-icon" onClick={() => setBrokerPreview(null)}>✕</button>
            </div>
            {brokerPreview.parse_errors?.length > 0 && (
              <ul className="upload-errors" style={{ marginBottom: 8 }}>
                {brokerPreview.parse_errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            )}
            {/* Bulk account type setter */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <span style={{ fontSize: '0.85rem', color: '#64748b' }}>Set all to:</span>
              {['IKE', 'IKZE', 'regular'].map(at => (
                <button key={at} className="btn-ghost btn-sm"
                        onClick={() => setBrokerPreview(p => ({
                          ...p,
                          preview: p.preview.map(r => ({ ...r, account_type: at }))
                        }))}>
                  {at}
                </button>
              ))}
            </div>
            <div style={{ overflowX: 'auto', marginBottom: 12 }}>
              <table className="tx-table" style={{ fontSize: '0.8rem' }}>
                <thead><tr>
                  <th>Date</th><th>Ticker</th><th>Type</th>
                  <th>Shares</th><th>Native price</th><th>Price PLN</th><th>Account</th><th>Notes</th>
                </tr></thead>
                <tbody>
                  {brokerPreview.preview.map((r, i) => (
                    <tr key={i}>
                      <td>{r.date}</td>
                      <td><strong>{r.ticker}</strong></td>
                      <td><span style={{ color: r.type === 'buy' ? '#22c55e' : '#ef4444' }}>{r.type}</span></td>
                      <td>{Number(r.shares).toFixed(4)}</td>
                      <td style={{color:'#64748b'}}>{Number(r.price_native).toFixed(4)} {r.currency}</td>
                      <td>{Number(r.price_pln).toFixed(2)}</td>
                      <td>
                        <select value={r.account_type} style={{ fontSize: '0.8rem', padding: '1px 4px' }}
                                onChange={e => setBrokerPreview(p => ({
                                  ...p,
                                  preview: p.preview.map((row, j) =>
                                    j === i ? { ...row, account_type: e.target.value } : row
                                  )
                                }))}>
                          <option value="IKE">IKE</option>
                          <option value="IKZE">IKZE</option>
                          <option value="regular">regular</option>
                        </select>
                      </td>
                      <td>{r.notes ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn-primary btn-sm" onClick={handleBrokerConfirm} disabled={brokerConfirming}>
                {brokerConfirming ? 'Importing...' : `Confirm import (${brokerPreview.preview.length} rows)`}
              </button>
              <button className="btn-ghost btn-sm" onClick={() => setBrokerPreview(null)}>Cancel</button>
            </div>
          </div>
        )}

        {/* Filters */}
        <div className="tx-filters">
          <select value={filters.type} onChange={e => setFilters(f => ({ ...f, type: e.target.value }))}>
            <option value="">All types</option>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
            <option value="dividend">Dividend</option>
          </select>
          <select value={filters.ticker} onChange={e => setFilters(f => ({ ...f, ticker: e.target.value }))}>
            <option value="">All tickers</option>
            {[...new Set(transactions.map(t => t.ticker))].sort().map(t =>
              <option key={t} value={t}>{t}</option>
            )}
          </select>
          <select value={filters.year} onChange={e => setFilters(f => ({ ...f, year: e.target.value }))}>
            <option value="">All years</option>
            {years.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          {(filters.type || filters.ticker || filters.year) && (
            <button className="btn-ghost btn-sm" onClick={() => setFilters({ ticker: '', type: '', year: '' })}>
              Clear filters
            </button>
          )}
        </div>

        {txLoading ? <p>Loading transactions...</p> :
         !transactions.length ? <p className="empty">No transactions yet.</p> : (
          <table className="tx-table">
            <thead>
              <tr>
                <th>Date</th><th>Ticker</th><th>Type</th><th>Shares</th>
                <th>Price</th><th>Total</th><th>Account</th><th>Notes</th><th></th>
              </tr>
            </thead>
            <tbody>
              {transactions.map(t => (
                <tr key={t.transaction_id} className={editId === t.transaction_id ? 'tx-row-editing' : ''}>
                  <td>{t.date}</td>
                  <td><strong>{t.ticker}</strong></td>
                  <td>
                    <span className="tx-type-badge" style={{ background: TYPE_COLOR[t.type] }}>
                      {TYPE_LABEL[t.type]}
                    </span>
                  </td>
                  <td>{parseFloat(t.shares).toFixed(4)}</td>
                  <td>{parseFloat(t.price_pln).toFixed(2)} PLN</td>
                  <td><strong>{(t.shares * t.price_pln).toLocaleString('pl-PL', { maximumFractionDigits: 0 })} PLN</strong></td>
                  <td><span className="account-badge">{t.account_type}</span></td>
                  <td className="tx-notes">{t.notes ?? ''}</td>
                  <td className="tx-row-btns">
                    <button className="btn-icon" title="Edit" onClick={() => startEdit(t)}>✎</button>
                    <button className="btn-icon btn-icon-del" title="Delete" onClick={() => setConfirmDel(t)}>✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* Delete ALL confirmation — two steps */}
        {confirmDelAll === 1 && (
          <div className="confirm-overlay">
            <div className="confirm-box">
              <p><strong>Delete all {transactions.length} transactions?</strong></p>
              <p className="confirm-warn">This will also clear all positions and IKE contributions. This cannot be undone.</p>
              <div className="confirm-btns">
                <button className="btn-danger" onClick={() => setConfirmDelAll(2)}>Yes, delete all</button>
                <button className="btn-ghost" onClick={() => setConfirmDelAll(0)}>Cancel</button>
              </div>
            </div>
          </div>
        )}
        {confirmDelAll === 2 && (
          <div className="confirm-overlay">
            <div className="confirm-box">
              <p><strong>Are you absolutely sure?</strong></p>
              <p className="confirm-warn">All {transactions.length} transactions, positions, and IKE contribution history will be permanently deleted.</p>
              <div className="confirm-btns">
                <button className="btn-danger" onClick={() => delAllMutation.mutate()}
                        disabled={delAllMutation.isPending}>
                  {delAllMutation.isPending ? 'Deleting...' : 'Yes, delete everything'}
                </button>
                <button className="btn-ghost" onClick={() => setConfirmDelAll(0)}>Cancel</button>
              </div>
            </div>
          </div>
        )}

        {/* Delete single confirmation */}
        {confirmDel && (
          <div className="confirm-overlay">
            <div className="confirm-box">
              <p>Delete <strong>{confirmDel.type}</strong> of <strong>{confirmDel.shares} {confirmDel.ticker}</strong> on {confirmDel.date}?</p>
              <p className="confirm-warn">This will reverse the position calculation.</p>
              <div className="confirm-btns">
                <button className="btn-danger" onClick={() => delMutation.mutate(confirmDel.transaction_id)}
                        disabled={delMutation.isPending}>
                  {delMutation.isPending ? 'Deleting...' : 'Delete'}
                </button>
                <button className="btn-ghost" onClick={() => setConfirmDel(null)}>Cancel</button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Add / Edit form */}
      {showForm && (
        <div className="card">
          <h3>{editId ? t('portfolio.edit') : t('portfolio.addTransaction')}</h3>
          <form className="tx-form" onSubmit={handleSubmit}>
            <div>
              <label>{t('portfolio.date')}</label>
              <input type="date" required value={form.date}
                     onChange={e => setForm({ ...form, date: e.target.value })} />
            </div>
            <div>
              <label>{t('portfolio.type')}</label>
              <select value={form.type} onChange={e => setForm({ ...form, type: e.target.value })}>
                <option value="buy">{t('portfolio.buy')}</option>
                <option value="sell">{t('portfolio.sell')}</option>
                <option value="dividend">{t('portfolio.dividend')}</option>
                <option value="deposit">{t('portfolio.deposit')}</option>
              </select>
            </div>
            <div>
              <label>{t('portfolio.account')}</label>
              <select value={form.account_type} onChange={e => setForm({ ...form, account_type: e.target.value })}>
                <option value="IKE">IKE</option>
                <option value="IKZE">IKZE</option>
                {form.type !== 'deposit' && <option value="regular">Regular</option>}
              </select>
            </div>

            {form.type === 'deposit' ? (
              <div>
                <label>{t('portfolio.depositAmount')}</label>
                <input type="number" placeholder="0.00" step="0.01" min="0.01" required
                       value={form.amount_pln ?? ''}
                       onChange={e => setForm({ ...form, amount_pln: e.target.value })} />
              </div>
            ) : (
              <>
                <div className="ticker-field">
                  <label>{t('portfolio.ticker')}</label>
                  <input placeholder="e.g. VWCE.DE" required list="ticker-list"
                         value={form.ticker}
                         onChange={e => setForm({ ...form, ticker: e.target.value.toUpperCase() })} />
                  <datalist id="ticker-list">
                    {availableTickers.map(t => <option key={t.ticker} value={t.ticker}>{t.name && t.name !== t.ticker ? t.name : ''}</option>)}
                  </datalist>
                </div>
                <div>
                  <label>{t('portfolio.shares')}</label>
                  <input type="number" placeholder="0.0000" step="0.0001" required
                         value={form.shares} onChange={e => setForm({ ...form, shares: e.target.value })} />
                </div>
                <div>
                  <label>
                    {t('portfolio.pricePln')}
                    {priceLoading && <span className="price-fetching"> fetching...</span>}
                    {priceHint && !priceLoading && (
                      <button type="button" className="price-autofill-btn"
                              onClick={() => setForm(f => ({ ...f, price_pln: priceHint.price_pln }))}>
                        Use {priceHint.price_pln.toFixed(2)} PLN
                        <span className="price-hint-meta">
                          ({priceHint.price_native} {priceHint.currency} · {priceHint.price_date})
                        </span>
                      </button>
                    )}
                  </label>
                  <input type="number" placeholder="0.00" step="0.01" required
                         value={form.price_pln} onChange={e => setForm({ ...form, price_pln: e.target.value })} />
                </div>
                {form.shares && form.price_pln && (
                  <div className="tx-total-preview">
                    Total: <strong>{(parseFloat(form.shares) * parseFloat(form.price_pln)).toLocaleString('pl-PL', { maximumFractionDigits: 2 })} PLN</strong>
                  </div>
                )}
              </>
            )}

            <div className="tx-form-notes">
              <label>{t('portfolio.notes')}</label>
              <input placeholder="Optional" value={form.notes}
                     onChange={e => setForm({ ...form, notes: e.target.value })} />
            </div>
            <div className="tx-form-btns">
              <button type="submit" className="btn-primary"
                      disabled={addMutation.isPending || editMutation.isPending}>
                {(addMutation.isPending || editMutation.isPending) ? t('common.loading') : editId ? t('portfolio.save') : t('portfolio.save')}
              </button>
              {editId && <button type="button" className="btn-ghost" onClick={cancelEdit}>{t('portfolio.cancel')}</button>}
            </div>
          </form>
          {msg && <p className={msg.startsWith('Error') ? 'error' : 'success-msg'}>{msg}</p>}
        </div>
      )}
      {msg && !showForm && <p className={msg.startsWith('Error') ? 'error' : 'success-msg'} style={{padding:'0 0 1rem'}}>{msg}</p>}
    </div>
  )
}
