import { API_ORIGIN } from './api/config'
import { fetchApiJson } from './api/http'

/** Same origin as all other calls */
export const BASE_URL = API_ORIGIN

/** Full-URL fetch under the hood (no path-only requests). */
export async function fetchAPI(endpoint) {
  const path = endpoint.startsWith('/') ? endpoint : `/${endpoint}`
  return fetchApiJson(path)
}
