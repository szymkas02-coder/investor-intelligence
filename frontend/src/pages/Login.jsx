import { useAuth } from '../contexts/AuthContext'
import { Navigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

export default function Login() {
  const { user } = useAuth()
  const { t } = useTranslation()
  if (user) return <Navigate to="/dashboard" replace />

  function handleLogin() {
    window.location.href = '/auth/login'
  }

  function handleDevLogin() {
    sessionStorage.setItem('access_token', 'dev-token')
    window.location.href = '/dashboard'
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
