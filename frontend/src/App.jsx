import { BrowserRouter, Routes, Route, Navigate, NavLink } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import Login     from './pages/Login'
import Dashboard from './pages/Dashboard'
import Decision  from './pages/Decision'
import Portfolio from './pages/Portfolio'
import History   from './pages/History'
import Situation from './pages/Situation'
import './App.css'

function RequireAuth({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="loading">Loading...</div>
  if (!user) return <Navigate to="/login" replace />
  return children
}

function Nav() {
  const { user, logout } = useAuth()
  return (
    <nav className="nav">
      <span className="nav-brand">Investor Intelligence</span>
      <div className="nav-links">
        <NavLink to="/dashboard">Dashboard</NavLink>
        <NavLink to="/decision">Decision</NavLink>
        <NavLink to="/situation">Situation</NavLink>
        <NavLink to="/portfolio">Portfolio</NavLink>
        <NavLink to="/history">History</NavLink>
      </div>
      <div className="nav-user">
        {user?.dev_mode && <span className="dev-badge">DEV</span>}
        <button onClick={logout} className="btn-ghost">Sign out</button>
      </div>
    </nav>
  )
}

function Layout({ children }) {
  return (
    <>
      <Nav />
      <main className="main">{children}</main>
    </>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/auth/callback" element={<OAuthCallback />} />
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={
            <RequireAuth><Layout><Dashboard /></Layout></RequireAuth>
          } />
          <Route path="/decision" element={
            <RequireAuth><Layout><Decision /></Layout></RequireAuth>
          } />
          <Route path="/portfolio" element={
            <RequireAuth><Layout><Portfolio /></Layout></RequireAuth>
          } />
          <Route path="/history" element={
            <RequireAuth><Layout><History /></Layout></RequireAuth>
          } />
          <Route path="/situation" element={
            <RequireAuth><Layout><Situation /></Layout></RequireAuth>
          } />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

// Handles the Google OAuth redirect — extracts token from URL query param
function OAuthCallback() {
  const { login } = useAuth()
  const params = new URLSearchParams(window.location.search)
  const token  = params.get('access_token')
  if (token) login(token)
  return <Navigate to="/dashboard" replace />
}
