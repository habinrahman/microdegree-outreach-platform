export function safe(v: unknown): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

export function cleanReplyMessage(msg: string | null | undefined): string {
  if (msg == null || msg === "") return "";
  return String(msg).split("-----Original Message-----")[0].trim();
}

export function normalizeCampaignFields(c: Record<string, unknown>): Record<string, unknown> {
  const companyRaw = c.company ?? c.hr_company ?? c.organization;
  const emailRaw = c.hr_email ?? c.email;
  return {
    ...c,
    company: companyRaw != null && companyRaw !== "" ? companyRaw : "—",
    hr_email: emailRaw != null && emailRaw !== "" ? emailRaw : "—",
  };
}
