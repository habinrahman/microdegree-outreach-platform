import { API_ORIGIN } from './config'

/** Build full URL — never pass a path-only string to fetch(). */
export function apiUrl(path) {
  if (path.startsWith('http://') || path.startsWith('https://')) return path
  const p = path.startsWith('/') ? path : `/${path}`
  return `${API_ORIGIN}${p}`
}

/**
 * GET JSON using a full URL (via apiUrl).
 * @param {string} path - '/analytics/summary' or absolute URL
 * @param {Record<string, string | number | boolean>} [searchParams] - query string
 */
export async function fetchApiJson(path, searchParams) {
  let url = apiUrl(path)
  if (searchParams && Object.keys(searchParams).length > 0) {
    const u = new URL(url)
    for (const [k, v] of Object.entries(searchParams)) {
      u.searchParams.set(k, String(v))
    }
    url = u.toString()
  }

  console.log('Calling API:', url)
  const res = await fetch(url)
  if (!res.ok) {
    const text = await res.text()
    const err = new Error(text || `HTTP ${res.status}`)
    console.error('API ERROR:', err)
    throw err
  }
  const data = await res.json()
  console.log('Response:', data)
  return data
}
