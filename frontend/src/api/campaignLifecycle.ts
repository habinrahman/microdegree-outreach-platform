import { safeGet } from "@/api/api";

export type LifecycleStatusCount = {
  status: string;
  count: number;
  is_terminal: boolean;
};

export type LifecycleUnknownStatusCount = {
  status: string;
  count: number;
};

export type LifecycleEdge = {
  source: string;
  target: string;
};

export type CampaignLifecycleVisualization = {
  computed_at_utc: string;
  total_campaign_rows: number;
  status_counts: LifecycleStatusCount[];
  unknown_status_counts: LifecycleUnknownStatusCount[];
  edges: LifecycleEdge[];
  self_loop_statuses: string[];
  terminal_statuses: string[];
  bulk_transitions: string[];
  mermaid_state_diagram: string;
};

export function fetchCampaignLifecycle(): Promise<CampaignLifecycleVisualization> {
  return safeGet<CampaignLifecycleVisualization>("/campaigns/lifecycle");
}
