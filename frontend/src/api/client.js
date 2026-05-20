import axios from 'axios'

// Dev: call backend directly on port 8000 (no Vite proxy — it drops concurrent connections)
// Prod: set VITE_API_URL to the Cloud Run URL
const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

const client = axios.create({ baseURL: BASE_URL })

// Attach JWT on every request
client.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// On 401, clear token — let AuthContext and React Router handle redirect
client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      sessionStorage.removeItem('access_token')
    }
    return Promise.reject(err)
  }
)

export default client
