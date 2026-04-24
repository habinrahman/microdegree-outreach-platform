import { api, safeGet } from "./api";

export async function listStudents(params?: { include_demo?: boolean }) {
  const d = await safeGet<unknown[]>("/students/", params as Record<string, unknown> | undefined);
  if (!Array.isArray(d)) throw new Error("GET /students/: expected JSON array");
  return d;
}

export async function createStudent(formData: FormData) {
  const { data } = await api.post("/students/", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

/** Soft delete: sets student status to inactive (DELETE /students/:id). */
export async function deactivateStudent(id: string) {
  const { data } = await api.delete(`/students/${id}`);
  return data;
}

/** @deprecated use deactivateStudent */
export const deleteStudent = deactivateStudent;

export async function updateStudent(id: string, payload: Record<string, unknown>) {
  const { data } = await api.put(`/students/${id}`, payload);
  return data;
}

export async function startGmailOAuth(studentId: string) {
  const { data } = await api.get<{ auth_url?: string }>(`/oauth/gmail/start`, {
    params: { student_id: studentId },
  });
  const url = String(data?.auth_url ?? "").trim();
  if (!url) throw new Error("OAuth start failed: missing auth_url");
  return { auth_url: url };
}

export type TemplateType = "INITIAL" | "FOLLOWUP_1" | "FOLLOWUP_2" | "FOLLOWUP_3";

export type StudentTemplate = {
  template_type: TemplateType;
  subject: string;
  body: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export type StudentTemplateBundle = Record<TemplateType, StudentTemplate | null>;

export async function getStudentTemplates(studentId: string) {
  const data = await safeGet<StudentTemplateBundle>(`/students/${studentId}/templates`);
  return data;
}

export async function putStudentTemplates(
  studentId: string,
  patch: Partial<Record<TemplateType, { subject: string; body: string } | null>>
) {
  const { data } = await api.put<StudentTemplateBundle>(`/students/${studentId}/templates`, patch);
  return data;
}
