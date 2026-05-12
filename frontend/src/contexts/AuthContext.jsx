import { createContext, useContext, useState, useEffect } from 'react'
import client from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser]       = useState(null)   // { user_id, dev_mode }
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // On mount: check if we already have a valid token
    const token = sessionStorage.getItem('access_token')
    if (!token) { setLoading(false); return }

    client.get('/auth/me')
      .then(res => setUser(res.data))
      .catch(() => sessionStorage.removeItem('access_token'))
      .finally(() => setLoading(false))
  }, [])

  // Called by the OAuth callback page after receiving the token from the URL
  function login(token) {
    sessionStorage.setItem('access_token', token)
    client.get('/auth/me').then(res => setUser(res.data))
  }

  function logout() {
    sessionStorage.removeItem('access_token')
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
