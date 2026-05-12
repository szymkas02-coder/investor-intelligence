import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import client from '../api/client'
import ReactMarkdown from 'react-markdown'

function fetchSituation() {
  return client.get('/situation').then(r => r.data)
}
function postRefresh() {
  return client.post('/situation/refresh').then(r => r.data)
}
function postChat(message) {
  return client.post('/chat', { message }).then(r => r.data)
}

function TimeAgo({ isoString }) {
  if (!isoString) return <span className="time-ago">never</span>
  const dt = new Date(isoString)
  const diffMs = Date.now() - dt.getTime()
  const diffH  = Math.floor(diffMs / 3600000)
  const diffM  = Math.floor((diffMs % 3600000) / 60000)
  const label  = diffH > 0 ? `${diffH}h ${diffM}m ago` : `${diffM}m ago`
  return <span className="time-ago" title={dt.toLocaleString()}>{label}</span>
}

function NextUpdate({ isoString, intervalH }) {
  if (!isoString) return null
  const next = new Date(new Date(isoString).getTime() + intervalH * 3600000)
  const diffMs = next.getTime() - Date.now()
  if (diffMs <= 0) return <span className="next-update">update due</span>
  const h = Math.floor(diffMs / 3600000)
  const m = Math.floor((diffMs % 3600000) / 60000)
  return <span className="next-update">next update in {h > 0 ? `${h}h ${m}m` : `${m}m`}</span>
}

export default function Situation() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['situation'],
    queryFn:  fetchSituation,
    staleTime: 10 * 60 * 1000,
  })

  const refreshMutation = useMutation({
    mutationFn: postRefresh,
    onSuccess:  () => refetch(),
  })

  // Chat state
  const [messages, setMessages]   = useState([])
  const [input,    setInput]      = useState('')
  const [sending,  setSending]    = useState(false)
  const [chatErr,  setChatErr]    = useState(null)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSend(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || sending) return
    setInput('')
    setChatErr(null)
    setMessages(m => [...m, { role: 'user', text }])
    setSending(true)
    try {
      const res = await postChat(text)
      setMessages(m => [...m, { role: 'assistant', text: res.reply }])
    } catch (err) {
      const detail = err.response?.data?.detail ?? err.message
      setChatErr(detail)
      setMessages(m => [...m, { role: 'assistant', text: `Error: ${detail}`, error: true }])
    } finally {
      setSending(false)
    }
  }

  const pulse    = data?.pulse
  const briefing = data?.briefing

  return (
    <div className="situation-page">

      {/* ── News Pulse ── */}
      <div className="card situation-card">
        <div className="situation-header">
          <h3>Latest News Pulse</h3>
          <div className="situation-meta">
            {pulse?.created_at
              ? <><TimeAgo isoString={pulse.created_at} /> · <NextUpdate isoString={pulse.created_at} intervalH={6} /></>
              : <span className="time-ago">no data yet</span>
            }
            <button
              className="btn-ghost btn-sm"
              onClick={() => refreshMutation.mutate()}
              disabled={refreshMutation.isPending}
            >
              {refreshMutation.isPending ? 'Refreshing…' : '↻ Refresh'}
            </button>
          </div>
        </div>

        {refreshMutation.isError && (
          <p className="situation-err">{refreshMutation.error?.response?.data?.detail ?? 'Refresh failed.'}</p>
        )}

        {isLoading ? <p className="loading-text">Loading…</p> :
         pulse?.content
          ? <div className="situation-content"><ReactMarkdown>{pulse.content}</ReactMarkdown></div>
          : <p className="empty">No pulse data yet. Click Refresh to generate the first one.</p>
        }

        <p className="situation-powered">Powered by Gemini 2.5 Flash + Google Search</p>
      </div>

      {/* ── Weekly Briefing ── */}
      <div className="card situation-card">
        <div className="situation-header">
          <h3>Weekly Briefing</h3>
          <div className="situation-meta">
            {briefing?.created_at
              ? <><TimeAgo isoString={briefing.created_at} /> · <NextUpdate isoString={briefing.created_at} intervalH={168} /></>
              : <span className="time-ago">no data yet</span>
            }
          </div>
        </div>

        {isLoading ? <p className="loading-text">Loading…</p> :
         briefing?.content
          ? <div className="situation-content"><ReactMarkdown>{briefing.content}</ReactMarkdown></div>
          : <p className="empty">No weekly briefing yet. The first one will be generated on Sunday.</p>
        }

        <p className="situation-powered">Powered by Gemini 2.5 Flash + Google Search · Updated weekly</p>
      </div>

      {/* ── Chat ── */}
      <div className="card situation-card chat-card">
        <div className="situation-header">
          <h3>AI Assistant</h3>
          <span className="situation-powered" style={{ marginTop: 0 }}>Powered by Gemini 3 Flash</span>
        </div>

        <div className="chat-messages">
          {messages.length === 0 && (
            <p className="chat-placeholder">
              Ask me anything about the current macro situation, the app's signals, or your VWCE investment strategy.
            </p>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`chat-msg chat-msg-${m.role}${m.error ? ' chat-msg-error' : ''}`}>
              <span className="chat-role">{m.role === 'user' ? 'You' : 'Assistant'}</span>
              <div className="chat-text">
                {m.role === 'assistant'
                  ? <ReactMarkdown>{m.text}</ReactMarkdown>
                  : <p>{m.text}</p>
                }
              </div>
            </div>
          ))}
          {sending && (
            <div className="chat-msg chat-msg-assistant">
              <span className="chat-role">Assistant</span>
              <div className="chat-text chat-thinking">Thinking…</div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <form className="chat-form" onSubmit={handleSend}>
          <input
            className="chat-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask about macro, signals, or your portfolio…"
            disabled={sending}
          />
          <button className="btn-primary" type="submit" disabled={sending || !input.trim()}>
            Send
          </button>
        </form>
      </div>

    </div>
  )
}
