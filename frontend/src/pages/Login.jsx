import { useAuth } from '../contexts/AuthContext'
import { Navigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import client from '../api/client'

export default function Login() {
  const { user, login } = useAuth()
  const { t } = useTranslation()
  if (user && !user.is_guest) return <Navigate to="/dashboard" replace />

  function handleLogin() {
    window.location.href = '/auth/login'
  }

  async function handleDevLogin() {
    try {
      const res = await client.post('/auth/guest')
      login(res.data.access_token)
    } catch {
      // fallback for local dev where backend may not need auth
      login('dev-token')
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <h1>{t('nav.brand')}</h1>
        <p className="subtitle">{t('login.subtitle')}</p>
        <button className="btn-primary" onClick={handleLogin}>
          {t('login.signIn')}
        </button>
        <button className="btn-ghost" onClick={handleDevLogin}
                style={{ marginTop: '0.5rem', fontSize: '0.8rem' }}>
          {t('login.devMode')}
        </button>
      </div>
    </div>
  )
}
