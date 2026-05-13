import { useAuth } from '../contexts/AuthContext'
import { Navigate } from 'react-router-dom'

export default function Login() {
  const { user } = useAuth()
  if (user) return <Navigate to="/dashboard" replace />

  function handleLogin() {
    // Redirect to FastAPI /auth/login which redirects to Google
    window.location.href = '/auth/login'
  }

  // Dev mode: just hit /auth/me directly — backend returns dev user
  function handleDevLogin() {
    sessionStorage.setItem('access_token', 'dev-token')
    window.location.href = '/dashboard'
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <h1>Investor Intelligence</h1>
        <p className="subtitle">Monthly IKE investment decisions, macro-informed.</p>
        <button className="btn-primary" onClick={handleLogin}>
          Sign in with Google
        </button>
        <button className="btn-ghost" onClick={handleDevLogin}
                style={{ marginTop: '0.5rem', fontSize: '0.8rem' }}>
          Dev mode (no auth)
        </button>
      </div>
    </div>
  )
}
