import { useState } from 'react'

export default function ChartCard({ title, plain, technical, chart, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  const [mode, setMode] = useState('plain') // 'plain' | 'technical'

  return (
    <div style={{
      background: '#fff', borderRadius: 10, border: '1px solid #e2e8f0',
      marginBottom: '1.2rem', overflow: 'hidden',
    }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '0.85rem 1.1rem', cursor: 'pointer',
          background: open ? '#f8fafc' : '#fff', borderBottom: open ? '1px solid #e2e8f0' : 'none',
        }}
      >
        <span style={{ fontWeight: 600, fontSize: '0.95rem', color: '#1e293b' }}>{title}</span>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          {open && (plain || technical) && (
            <span
              onClick={e => { e.stopPropagation(); setMode(m => m === 'plain' ? 'technical' : 'plain') }}
              style={{
                fontSize: '0.72rem', padding: '0.2rem 0.55rem', borderRadius: 4,
                border: '1px solid #cbd5e1', background: '#fff', cursor: 'pointer',
                color: '#475569', userSelect: 'none',
              }}
            >
              {mode === 'plain' ? '⚙ Technical' : '💬 Plain language'}
            </span>
          )}
          <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>{open ? '▲' : '▼'}</span>
        </div>
      </div>

      {open && (
        <div style={{ padding: '1rem 1.1rem' }}>
          {(plain || technical) && (
            <div style={{
              padding: '0.7rem 0.9rem', borderRadius: 6, marginBottom: '1rem',
              background: mode === 'plain' ? '#f0f9ff' : '#fafaf9',
              borderLeft: `3px solid ${mode === 'plain' ? '#0ea5e9' : '#78716c'}`,
              fontSize: '0.83rem', color: '#334155', lineHeight: 1.6,
            }}>
              {mode === 'plain' ? plain : technical}
            </div>
          )}
          {chart}
        </div>
      )}
    </div>
  )
}
