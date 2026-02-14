/** API client — fetch wrapper for RefCheck backend. */

import type {
  Claim,
  EvidenceResponse,
  ManuscriptResponse,
  ReferencesResponse,
  ReportPreview,
  ResultsResponse,
  Session,
  SessionListResponse,
  VerificationResult,
} from "./types";

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

export async function getResults(
  sessionId: string,
  filters?: {
    verdict?: string;
    priority?: string;
    min_confidence?: number;
    sort?: string;
    page?: number;
    per_page?: number;
  }
): Promise<ResultsResponse> {
  const params = new URLSearchParams();
  if (filters?.verdict) params.set("verdict", filters.verdict);
  if (filters?.priority) params.set("priority", filters.priority);
  if (filters?.min_confidence !== undefined)
    params.set("min_confidence", String(filters.min_confidence));
  if (filters?.sort) params.set("sort", filters.sort);
  if (filters?.page) params.set("page", String(filters.page));
  if (filters?.per_page) params.set("per_page", String(filters.per_page));

  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/results?${params}`
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

export async function overrideVerdict(
  sessionId: string,
  claimId: number,
  verdict: string,
  reason: string
): Promise<VerificationResult> {
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/results/${claimId}/override`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verdict, reason }),
    }
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
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

export async function getClaims(sessionId: string): Promise<Claim[]> {
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/claims`
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

export async function updateClaim(
  sessionId: string,
  claimId: number,
  updates: Partial<Claim>
): Promise<Claim> {
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/claims/${claimId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    }
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

export async function deleteClaim(
  sessionId: string,
  claimId: number
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/claims/${claimId}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
}

export async function getManuscript(
  sessionId: string
): Promise<ManuscriptResponse> {
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/manuscript`
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

export async function getEvidence(
  sessionId: string,
  claimId: number
): Promise<EvidenceResponse> {
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/evidence/${claimId}`
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}
