import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import client from '../api/client'

function fetchSituation() {
  return client.get('/situation').then(r => r.data)
}
function postRefresh(lang) {
  return client.post(`/situation/refresh?lang=${lang}`).then(r => r.data)
}
function postChat(message) {
  return client.post('/chat', { message }).then(r => r.data)
}
function fetchChatHistory() {
  return client.get('/chat/history').then(r => r.data)
}

function TimeAgo({ isoString }) {
  const { t } = useTranslation()
  if (!isoString) return <span style={{ color: '#94a3b8', fontSize: '0.82rem' }}>{t('common.never')}</span>
  const dt = new Date(isoString)
  const diffMs = Date.now() - dt.getTime()
  const diffH  = Math.floor(diffMs / 3600000)
  const diffM  = Math.floor((diffMs % 3600000) / 60000)
  const label  = diffH > 0 ? t('common.timeAgoH', { h: diffH, m: diffM }) : t('common.timeAgoM', { m: diffM })
  return <span style={{ color: '#64748b', fontSize: '0.82rem' }} title={dt.toLocaleString()}>{label}</span>
}

function NextUpdate({ isoString, intervalH }) {
  const { t } = useTranslation()
  if (!isoString) return null
  const next = new Date(new Date(isoString).getTime() + intervalH * 3600000)
  const diffMs = next.getTime() - Date.now()
  if (diffMs <= 0) return <span style={{ color: '#f97316', fontSize: '0.8rem', fontWeight: 600 }}>{t('common.updateDue')}</span>
  const h = Math.floor(diffMs / 3600000)
  const m = Math.floor((diffMs % 3600000) / 60000)
  return <span style={{ color: '#94a3b8', fontSize: '0.8rem' }}>{t('common.nextUpdateIn')} {h > 0 ? `${h}h ${m}m` : `${m}m`}</span>
}

function SourceBadge({ url }) {
  let host = url
  try { host = new URL(url).hostname.replace(/^www\./, '') } catch { /* keep raw */ }
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" style={{
      display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
      padding: '0.1rem 0.5rem', margin: '0.15rem 0.2rem 0 0',
      background: '#eff6ff', color: '#1e40af', border: '1px solid #bfdbfe',
      borderRadius: 999, fontSize: '0.7rem', textDecoration: 'none',
      transition: 'background 0.15s',
    }}
      onMouseEnter={e => e.currentTarget.style.background = '#dbeafe'}
      onMouseLeave={e => e.currentTarget.style.background = '#eff6ff'}
    >
      {host}
    </a>
  )
}

const markdownComponents = {
  a: ({ href, children }) => <SourceBadge url={href}>{children}</SourceBadge>,
  ul: ({ children }) => <ul style={{ paddingLeft: '1.2rem', margin: '0.25rem 0' }}>{children}</ul>,
  li: ({ children }) => <li style={{ marginBottom: '0.5rem', lineHeight: 1.65 }}>{children}</li>,
  p:  ({ children }) => <p style={{ margin: '0.4rem 0', lineHeight: 1.65 }}>{children}</p>,
  h2: ({ children }) => <h2 style={{ fontSize: '1rem', margin: '1.1rem 0 0.4rem', color: '#0f172a' }}>{children}</h2>,
  h3: ({ children }) => <h3 style={{ fontSize: '0.95rem', margin: '0.9rem 0 0.35rem', color: '#1e293b' }}>{children}</h3>,
}

function ChatBubble({ role, text, error, t }) {
  const isUser = role === 'user'
  const avatar = isUser ? '🧑' : '🤖'

  return (
    <div style={{
      display: 'flex', flexDirection: isUser ? 'row-reverse' : 'row',
      alignItems: 'flex-end', gap: '0.5rem', marginBottom: '0.85rem',
    }}>
      <div style={{
        fontSize: '1.1rem', width: 30, height: 30, lineHeight: '30px',
        textAlign: 'center', borderRadius: '50%',
        background: isUser ? '#dbeafe' : '#f1f5f9', flexShrink: 0,
      }}>
        {avatar}
      </div>
      <div style={{ maxWidth: '78%' }}>
        <div style={{
          fontSize: '0.68rem', color: '#94a3b8', textTransform: 'uppercase',
          letterSpacing: '0.04em', marginBottom: '0.2rem',
          textAlign: isUser ? 'right' : 'left',
        }}>
          {isUser ? t('situation.you') : t('situation.assistant')}
        </div>
        <div style={{
          padding: '0.6rem 0.95rem', borderRadius: 14,
          fontSize: '0.9rem', lineHeight: 1.55,
          background: error ? '#fee2e2' : isUser ? '#3b82f6' : '#f1f5f9',
          color: error ? '#991b1b' : isUser ? '#fff' : '#1e293b',
          borderBottomRightRadius: isUser ? 4 : 14,
          borderBottomLeftRadius:  isUser ? 14 : 4,
          wordBreak: 'break-word',
        }}>
          {isUser
            ? <p style={{ margin: 0 }}>{text}</p>
            : <ReactMarkdown components={markdownComponents}>{text}</ReactMarkdown>}
        </div>
      </div>
    </div>
  )
}

function ChatExamples({ onPick, t }) {
  const prompts = [
    t('situation.examplePrompt1'),
    t('situation.examplePrompt2'),
    t('situation.examplePrompt3'),
  ]
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      padding: '1.2rem 0.5rem', gap: '0.75rem', minHeight: 180,
    }}>
      <p style={{ color: '#94a3b8', fontSize: '0.85rem', margin: 0, textAlign: 'center' }}>
        {t('situation.chatPlaceholder')}
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: '0.45rem', maxWidth: 600 }}>
        {prompts.map((p, i) => (
          <button
            key={i}
            onClick={() => onPick(p)}
            style={{
              background: '#f8fafc', border: '1px solid #e2e8f0',
              borderRadius: 999, padding: '0.45rem 0.85rem',
              fontSize: '0.78rem', color: '#475569', cursor: 'pointer',
              transition: 'background 0.15s, border-color 0.15s',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.background = '#eff6ff'
              e.currentTarget.style.borderColor = '#bfdbfe'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.background = '#f8fafc'
              e.currentTarget.style.borderColor = '#e2e8f0'
            }}
          >
            {p}
          </button>
        ))}
      </div>
    </div>
  )
}

export default function Situation() {
  const { t, i18n } = useTranslation()
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['situation'],
    queryFn:  fetchSituation,
    staleTime: 10 * 60 * 1000,
  })

  const refreshMutation = useMutation({
    mutationFn: () => postRefresh('pl'),
    onSuccess:  () => refetch(),
  })

  const [messages, setMessages]   = useState([])
  const [input,    setInput]      = useState('')
  const [sending,  setSending]    = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    if (historyLoaded) return
    fetchChatHistory()
      .then(data => {
        if (data.messages?.length) setMessages(data.messages)
        setHistoryLoaded(true)
      })
      .catch(() => setHistoryLoaded(true))
  }, [historyLoaded])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function sendMessage(text) {
    if (!text || sending) return
    setMessages(m => [...m, { role: 'user', text }])
    setSending(true)
    try {
      const res = await postChat(text)
      setMessages(m => [...m, { role: 'assistant', text: res.reply }])
    } catch (err) {
      const detail = err.response?.data?.detail ?? err.message
      setMessages(m => [...m, { role: 'assistant', text: `Error: ${detail}`, error: true }])
    } finally {
      setSending(false)
    }
  }

  async function handleSend(e) {
    e.preventDefault()
    const text = input.trim()
    setInput('')
    await sendMessage(text)
  }

  function handlePickExample(text) {
    sendMessage(text)
  }

  const pulse    = data?.pulse
  const briefing = data?.briefing

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '1.5rem 1rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

      {/* ── PULSE CARD ── */}
      <div style={{
        background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0',
        padding: '1.2rem 1.4rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.85rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <span style={{
              background: '#dbeafe', color: '#1e40af',
              padding: '0.2rem 0.6rem', borderRadius: 5,
              fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.04em',
            }}>
              {t('situation.dailyPulse', 'PULS DZIENNY')}
            </span>
            <h3 style={{ margin: 0, color: '#0f172a', fontSize: '1.05rem' }}>{t('situation.pulse')}</h3>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            {pulse?.created_at
              ? <><TimeAgo isoString={pulse.created_at} /><NextUpdate isoString={pulse.created_at} intervalH={6} /></>
              : <span style={{ color: '#94a3b8', fontSize: '0.82rem' }}>{t('common.never')}</span>
            }
            <button
              style={{
                background: '#fff', border: '1px solid #e2e8f0',
                borderRadius: 6, padding: '0.3rem 0.75rem',
                fontSize: '0.78rem', color: '#475569', cursor: 'pointer',
              }}
              onClick={() => refreshMutation.mutate()}
              disabled={refreshMutation.isPending}
            >
              {refreshMutation.isPending ? t('situation.refreshing') : `↻ ${t('situation.refresh')}`}
            </button>
          </div>
        </div>

        {refreshMutation.isError && (
          <p style={{ color: '#dc2626', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
            {refreshMutation.error?.response?.data?.detail ?? t('situation.refreshFailed')}
          </p>
        )}

        {isLoading ? (
          <p style={{ color: '#94a3b8', fontSize: '0.9rem' }}>{t('common.loading')}</p>
        ) : pulse?.content ? (
          <div style={{ fontSize: '0.92rem', color: '#334155', maxWidth: 750 }}>
            <ReactMarkdown components={markdownComponents}>{pulse.content}</ReactMarkdown>
          </div>
        ) : (
          <p style={{ color: '#94a3b8', fontStyle: 'italic' }}>{t('situation.noPulse')}</p>
        )}

        <p style={{ fontSize: '0.72rem', color: '#94a3b8', marginTop: '0.85rem', marginBottom: 0 }}>
          {t('situation.poweredPulse')} · <span title={t('situation.langNote')}>{t('situation.langLabel')}</span>
        </p>
      </div>

      {/* ── BRIEFING CARD ── */}
      <div style={{
        background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0',
        padding: '1.2rem 1.4rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.85rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <span style={{
              background: '#fef3c7', color: '#92400e',
              padding: '0.2rem 0.6rem', borderRadius: 5,
              fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.04em',
            }}>
              {t('situation.weeklyBadge', 'TYGODNIOWY')}
            </span>
            <h3 style={{ margin: 0, color: '#0f172a', fontSize: '1.05rem' }}>{t('situation.briefing')}</h3>
          </div>
          <div>
            {briefing?.created_at
              ? <><TimeAgo isoString={briefing.created_at} /> <NextUpdate isoString={briefing.created_at} intervalH={168} /></>
              : <span style={{ color: '#94a3b8', fontSize: '0.82rem' }}>{t('common.never')}</span>
            }
          </div>
        </div>

        {isLoading ? (
          <p style={{ color: '#94a3b8', fontSize: '0.9rem' }}>{t('common.loading')}</p>
        ) : briefing?.content ? (
          <div style={{
            fontSize: '0.93rem', color: '#334155',
            fontFamily: 'Georgia, "Times New Roman", serif',
            maxWidth: 750, lineHeight: 1.75,
          }}>
            <ReactMarkdown components={markdownComponents}>{briefing.content}</ReactMarkdown>
          </div>
        ) : (
          <p style={{ color: '#94a3b8', fontStyle: 'italic' }}>{t('situation.noBriefing')}</p>
        )}

        <p style={{ fontSize: '0.72rem', color: '#94a3b8', marginTop: '0.85rem', marginBottom: 0 }}>
          {t('situation.poweredBriefing')} · <span title={t('situation.langNote')}>{t('situation.langLabel')}</span>
        </p>
      </div>

      {/* ── CHAT CARD ── */}
      <div style={{
        background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0',
        padding: '1.2rem 1.4rem', display: 'flex', flexDirection: 'column',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.85rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <span style={{
              background: '#dcfce7', color: '#166534',
              padding: '0.2rem 0.6rem', borderRadius: 5,
              fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.04em',
            }}>
              {t('situation.chatBadge', 'CHAT AI')}
            </span>
            <h3 style={{ margin: 0, color: '#0f172a', fontSize: '1.05rem' }}>{t('situation.chat')}</h3>
          </div>
          <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
            {t('situation.chatPowered')}
          </span>
        </div>

        <div style={{
          minHeight: 220, maxHeight: 460, overflowY: 'auto',
          padding: '0.5rem 0.2rem 0.75rem',
          marginBottom: '0.75rem',
          borderBottom: '1px solid #f1f5f9',
        }}>
          {messages.length === 0
            ? <ChatExamples onPick={handlePickExample} t={t} />
            : messages.map((m, i) => (
                <ChatBubble key={i} role={m.role} text={m.text} error={m.error} t={t} />
              ))
          }
          {sending && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.4rem 0.5rem' }}>
              <div style={{
                width: 30, height: 30, lineHeight: '30px', textAlign: 'center',
                borderRadius: '50%', background: '#f1f5f9', fontSize: '1.1rem',
              }}>🤖</div>
              <span style={{ color: '#94a3b8', fontStyle: 'italic', fontSize: '0.85rem' }}>
                {t('situation.thinking')}
              </span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={handleSend} style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder={t('situation.chatPlaceholder')}
            disabled={sending}
            style={{
              flex: 1, padding: '0.6rem 0.95rem',
              border: '1px solid #e2e8f0', borderRadius: 10,
              fontSize: '0.9rem', outline: 'none',
            }}
            onFocus={e => e.currentTarget.style.borderColor = '#3b82f6'}
            onBlur={e => e.currentTarget.style.borderColor = '#e2e8f0'}
          />
          <button type="submit" disabled={sending || !input.trim()}
            style={{
              background: input.trim() && !sending ? '#3b82f6' : '#cbd5e1',
              color: '#fff', border: 'none', borderRadius: 10,
              padding: '0.6rem 1.2rem', fontSize: '0.9rem',
              fontWeight: 600, cursor: input.trim() && !sending ? 'pointer' : 'not-allowed',
            }}
          >
            {t('situation.send')}
          </button>
        </form>
      </div>
    </div>
  )
}
