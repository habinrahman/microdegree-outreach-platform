import axios from 'axios'
import { API_ORIGIN } from './config'

export const API_BASE_URL = API_ORIGIN

export const apiClient = axios.create({
  baseURL: API_ORIGIN,
  timeout: 45_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

function requestFullUrl(config) {
  const raw = config.url ?? ''
  if (raw.startsWith('http://') || raw.startsWith('https://')) return raw
  const base = (config.baseURL ?? '').replace(/\/$/, '')
  const path = raw.startsWith('/') ? raw : `/${raw}`
  return `${base}${path}`
}

apiClient.interceptors.request.use((config) => {
  console.log('Calling API:', requestFullUrl(config))
  return config
})

apiClient.interceptors.response.use(
  (response) => {
    console.log('Response:', response.data)
    return response
  },
  (error) => {
    console.error('API ERROR:', error)
    return Promise.reject(error)
  },
)

/** Human-readable message for UI (FastAPI often returns { detail: string | array }) */
export function formatApiError(err) {
  if (!err) return 'Request failed'
  if (err.code === 'ECONNABORTED' || err.message?.includes('timeout')) {
    return `Request timed out. Is the backend running at ${API_ORIGIN}?`
  }
  if (err.code === 'ERR_NETWORK' || err.message === 'Network Error') {
    return `Network error — check ${API_ORIGIN} and CORS (origin must include this Vite dev URL).`
  }
  const d = err.response?.data
  const detail = d?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((x) => x?.msg || x).join('; ') || err.message
  }
  return err.message || 'Request failed'
}
