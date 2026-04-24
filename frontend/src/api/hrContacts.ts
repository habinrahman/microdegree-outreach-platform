import axios from "axios";
import { api, safeGet } from "./api";

export type HrScoreReason = {
  code: string;
  label: string;
  impact: string;
  weight?: number | null;
};

export type HrContactRow = {
  id: string;
  name: string;
  company: string;
  email: string;
  domain?: string | null;
  status: string;
  is_valid: boolean;
  tier?: string;
  health_score?: number;
  opportunity_score?: number;
  health_reasons?: HrScoreReason[];
  opportunity_reasons?: HrScoreReason[];
  score_components?: Record<string, unknown>;
};

export type HrHealthDetail = HrContactRow & {
  hr_id: string;
  components?: Record<string, unknown>;
};

/** GET /hr-contacts — throws on failure. */
export async function listHrContacts(params?: {
  limit?: number;
  includeHealth?: boolean;
  tier?: string;
}) {
  const limit = params?.limit ?? 8000;
  const q: Record<string, string | number | boolean> = { limit };
  if (params?.includeHealth) q.include_health = true;
  if (params?.tier && params.tier !== "all") q.tier = params.tier;
  const d = await safeGet<HrContactRow[]>("/hr-contacts", q);
  if (!Array.isArray(d)) throw new Error("GET /hr-contacts: expected JSON array");
  return d;
}

export async function fetchHrHealthDetail(hrId: string) {
  return safeGet<HrHealthDetail>(`/hr-contacts/${hrId}/health`);
}

export async function uploadHrContactsCsv(formData: FormData) {
  try {
    const { data } = await api.post("/hr-contacts/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  } catch (e) {
    if (axios.isAxiosError(e) && e.response?.status === 404) {
      const { data } = await api.post("/hr/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return data;
    }
    throw e;
  }
}
