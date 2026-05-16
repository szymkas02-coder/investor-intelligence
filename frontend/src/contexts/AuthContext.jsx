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
    const token = sessionStorage.getItem('access_token')
    if (token) {
      // Existing token — verify it
      client.get('/auth/me')
        .then(res => { setUser(res.data); setLoading(false) })
        .catch(() => {
          sessionStorage.removeItem('access_token')
          _autoGuestLogin(setUser, setLoading)
        })
    } else {
      // No token — auto-login as guest so the app is publicly accessible
      _autoGuestLogin(setUser, setLoading)
    }
  }, [])

  // Called by the OAuth callback page after receiving the token from the URL
  function login(token) {
    sessionStorage.setItem('access_token', token)
    client.get('/auth/me').then(res => setUser(res.data))
  }

  function logout() {
    sessionStorage.removeItem('access_token')
    setUser(null)
    // Re-login as guest so the app stays usable after logout
    _autoGuestLogin(setUser, () => {})
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
