/** DOCX report download URL, regeneration and preview calls. */

import { API_BASE, APIError } from "./api-client";
import type { ReportPreview } from "./types";

export function getReportUrl(sessionId: string): string {
  return `${API_BASE}/api/sessions/${sessionId}/report`;
}

export async function regenerateReport(
  sessionId: string
): Promise<{ message: string; generated_at: string }> {
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/report/regenerate`,
    { method: "POST" }
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

export async function getReportPreview(
  sessionId: string
): Promise<ReportPreview> {
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/report/preview`
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}
