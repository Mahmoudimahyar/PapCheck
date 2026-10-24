/** Session lifecycle, pipeline start / events, library stats and health calls. */

import { API_BASE, APIError } from "./api-client";
import type { HealthResponse, LibraryStats, Session, SessionListResponse } from "./types";

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

export async function listSessions(
  page = 1,
  perPage = 20
): Promise<SessionListResponse> {
  const params = new URLSearchParams({
    page: String(page),
    per_page: String(perPage),
  });
  const res = await fetch(`${API_BASE}/api/sessions?${params}`);
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new APIError(res.status, await res.text());
}

export async function startPipeline(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/start`, {
    method: "POST",
  });
  if (!res.ok) throw new APIError(res.status, await res.text());
}

export function getEventsUrl(sessionId: string): string {
  return `${API_BASE}/api/sessions/${sessionId}/events`;
}

export async function getLibraryStats(): Promise<LibraryStats> {
  const res = await fetch(`${API_BASE}/api/library/stats`);
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

/** Service + per-role LLM status. `deep` makes one tiny real call per role. */
export async function getHealth(deep = false): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/api/health${deep ? "?deep=true" : ""}`);
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}
