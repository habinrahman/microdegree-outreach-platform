import { safeGet } from "./api";

export async function getAnalyticsSummary(params?: { include_demo?: boolean }) {
  return safeGet<Record<string, number | string>>(
    "/analytics/summary",
    params as Record<string, unknown> | undefined
  );
}

export async function getAnalyticsStudents(params?: { limit?: number; include_demo?: boolean }) {
  const d = await safeGet<unknown[]>(
    "/analytics/students",
    params as Record<string, unknown> | undefined
  );
  if (!Array.isArray(d)) throw new Error("GET /analytics/students: expected JSON array");
  return d;
}

export async function getAnalyticsHrs(params?: { limit?: number; include_demo?: boolean }) {
  const d = await safeGet<unknown[]>(
    "/analytics/hrs",
    params as Record<string, unknown> | undefined
  );
  if (!Array.isArray(d)) throw new Error("GET /analytics/hrs: expected JSON array");
  return d;
}

export async function getAnalyticsTemplates(params?: { include_demo?: boolean }) {
  const d = await safeGet<unknown[]>(
    "/analytics/templates",
    params as Record<string, unknown> | undefined
  );
  if (!Array.isArray(d)) throw new Error("GET /analytics/templates: expected JSON array");
  return d;
}
