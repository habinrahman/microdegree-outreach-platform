import axios from "axios";
import { api, safeGet } from "./api";

export type CampaignRow = Record<string, unknown> & {
  id?: string;
  student_id?: string;
  hr_id?: string;
  student_name?: string | null;
  company?: string | null;
  hr_email?: string | null;
  email_type?: string | null;
  status?: string | null;
  reply_status?: string | null;
  delivery_status?: string | null;
  sent_at?: string | null;
};

export async function listCampaigns(params?: Record<string, unknown>) {
  const d = await safeGet<unknown[]>("/campaigns", params);
  if (!Array.isArray(d)) throw new Error("GET /campaigns: expected JSON array");
  return d as CampaignRow[];
}

export async function patchCampaigns(payload: {
  campaign_ids: string[];
  status: "paused" | "cancelled";
}) {
  try {
    const { data } = await api.patch("/campaigns", payload);
    return data;
  } catch (e) {
    if (axios.isAxiosError(e) && e.response?.status === 404) {
      return { updated: 0, detail: "PATCH /campaigns not available on this API" };
    }
    throw e;
  }
}

export async function updateCampaignContent(
  id: string,
  payload: { subject: string; body: string }
) {
  const { data } = await api.put(`/campaigns/${id}`, payload);
  return data;
}
