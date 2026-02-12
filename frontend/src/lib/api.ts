/** API client — fetch wrapper for RefCheck backend. */

import type { ReferencesResponse, Session } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

class APIError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function createSession(
  manuscript: File,
  pdfs: File[]
): Promise<Session> {
  const formData = new FormData();
  formData.append("manuscript", manuscript);
  pdfs.forEach((pdf) => formData.append("pdfs", pdf));

  const res = await fetch(`${API_BASE}/api/sessions`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

export async function getSession(id: string): Promise<Session> {
  const res = await fetch(`${API_BASE}/api/sessions/${id}`);
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

export async function startPipeline(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/start`, {
    method: "POST",
  });
  if (!res.ok) throw new APIError(res.status, await res.text());
}

export async function getReferences(
  sessionId: string,
  status = "all",
  page = 1
): Promise<ReferencesResponse> {
  const params = new URLSearchParams({ status, page: String(page), per_page: "50" });
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/references?${params}`
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

export async function confirmMatch(
  sessionId: string,
  refId: number,
  confirmed: boolean
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/matches/${refId}/confirm`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmed }),
    }
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
}

export function getReportUrl(sessionId: string): string {
  return `${API_BASE}/api/sessions/${sessionId}/report`;
}

export function getEventsUrl(sessionId: string): string {
  return `${API_BASE}/api/sessions/${sessionId}/events`;
}
