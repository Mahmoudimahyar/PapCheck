/** Verification results, overrides, breakdowns, claims, manuscript and evidence calls. */

import { API_BASE, APIError } from "./api-client";
import type {
  CannotVerifyBreakdown,
  Claim,
  EvidenceResponse,
  ManuscriptResponse,
  PartialBreakdown,
  ResultsResponse,
  VerificationResult,
} from "./types";

export async function getResults(
  sessionId: string,
  filters?: {
    verdict?: string;
    priority?: string;
    min_confidence?: number;
    sort?: string;
    page?: number;
    per_page?: number;
    /** V5.4: a partial type, "unclassified", "guarded" or "guarded:<guard>". */
    partial_type?: string;
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
  if (filters?.partial_type) params.set("partial_type", filters.partial_type);

  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/results?${params}`
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

/** All pages of a filtered result list (the API caps a page at 200 rows). */
export async function getAllResults(
  sessionId: string,
  filters: { verdict?: string; priority?: string; partial_type?: string } = {}
): Promise<ResultsResponse> {
  const first = await getResults(sessionId, { ...filters, page: 1, per_page: 200 });
  const all = [...first.results];
  for (let page = 2; all.length < first.total; page++) {
    const next = await getResults(sessionId, { ...filters, page, per_page: 200 });
    if (next.results.length === 0) break;
    all.push(...next.results);
  }
  return { ...first, results: all };
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

export async function getCannotVerifyBreakdown(
  sessionId: string
): Promise<CannotVerifyBreakdown> {
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/cannot-verify-breakdown`
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

/** V5.4: partially supported results per sub-type, guarded supported results per guard. */
export async function getPartialBreakdown(sessionId: string): Promise<PartialBreakdown> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/partial-breakdown`);
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
