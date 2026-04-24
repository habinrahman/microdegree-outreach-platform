import axios from "axios";

/** Never throws — use for optional widgets so pages keep rendering. */
export function isAxios404(e: unknown): boolean {
  return axios.isAxiosError(e) && e.response?.status === 404;
}

export function getErrorDetail(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const d = e.response?.data as { detail?: string } | undefined;
    if (typeof d?.detail === "string") return d.detail;
    if (e.response?.status === 404) return "Not found (404)";
  }
  if (e instanceof Error) return e.message;
  return "Request failed";
}

export async function tryRequests<T>(
  factories: Array<() => Promise<T>>,
  fallback: T
): Promise<T> {
  for (const fn of factories) {
    try {
      const v = await fn();
      if (v !== undefined && v !== null) return v;
    } catch (e) {
      if (import.meta.env.DEV && isAxios404(e)) {
        console.debug("[safeApi] optional endpoint 404, trying next");
      }
    }
  }
  return fallback;
}
