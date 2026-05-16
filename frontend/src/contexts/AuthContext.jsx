import { createContext, useContext, useState, useEffect } from 'react'
import client from '../api/client'

const AuthContext = createContext(null)

async function _autoGuestLogin(setUser, setLoading) {
  try {
    const res = await client.post('/auth/guest')
    sessionStorage.setItem('access_token', res.data.access_token)
    const me = await client.get('/auth/me')
    setUser({ ...me.data, is_guest: true })
  } catch {
    // Guest login failed (e.g. local dev with no network) — stay unauthenticated
  } finally {
    setLoading(false)
  }
}

export function AuthProvider({ children }) {
  const [user, setUser]       = useState(null)   // { user_id, dev_mode, is_guest? }
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token        = sessionStorage.getItem('access_token')
    const didLogOut    = sessionStorage.getItem('explicit_logout')
    if (token) {
      client.get('/auth/me')
        .then(res => { setUser(res.data); setLoading(false) })
        .catch(() => {
          sessionStorage.removeItem('access_token')
          _autoGuestLogin(setUser, setLoading)
        })
    } else if (didLogOut) {
      // User explicitly logged out — stay on login page, don't auto-guest
      setLoading(false)
    } else {
      // First visit — auto-login as guest so app is publicly accessible
      _autoGuestLogin(setUser, setLoading)
    }
  }, [])

  // Called by the OAuth callback page after receiving the token from the URL
  function login(token) {
    sessionStorage.removeItem('explicit_logout')
    sessionStorage.setItem('access_token', token)
    client.get('/auth/me').then(res => setUser(res.data))
  }

  function logout() {
    sessionStorage.removeItem('access_token')
    sessionStorage.setItem('explicit_logout', '1')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
