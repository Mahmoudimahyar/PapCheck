/** Reference list, PDF matching / upload, reference links and source-issue calls. */

import { API_BASE, APIError } from "./api-client";
import type {
  Reference,
  ReferenceLinks,
  ReferencesResponse,
  RefreshMetadataResponse,
  SourceIssuesResponse,
  UploadPdfResponse,
} from "./types";

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

/** Every reference of a session (the API pages at 50). */
export async function getAllReferences(sessionId: string): Promise<Reference[]> {
  const first = await getReferences(sessionId, "all", 1);
  const all = [...first.references];
  const totalPages = Math.ceil(first.total / Math.max(first.per_page, 1));
  for (let p = 2; p <= totalPages; p++) {
    all.push(...(await getReferences(sessionId, "all", p)).references);
  }
  return all;
}

/**
 * V5.9: re-query the metadata APIs (abstract, open-access copy) for one reference.
 * A changed abstract starts a background re-verification of `claims_to_reverify`.
 */
export async function refreshReferenceMetadata(
  sessionId: string,
  refId: number
): Promise<RefreshMetadataResponse> {
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/references/${refId}/refresh-metadata`,
    { method: "POST" }
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

export async function getReferenceLinks(
  sessionId: string,
  refId: number
): Promise<ReferenceLinks> {
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/references/${refId}/links`
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

export async function uploadReferencePdf(
  sessionId: string,
  refId: number,
  file: File
): Promise<UploadPdfResponse> {
  const formData = new FormData();
  formData.append("pdf", file);
  const res = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/references/${refId}/upload-pdf`,
    { method: "POST", body: formData }
  );
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}

/** V5.2: duplicates, ambiguous citations, wrong / scanned / supplement PDFs, repaired titles. */
export async function getSourceIssues(sessionId: string): Promise<SourceIssuesResponse> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/source-issues`);
  if (!res.ok) throw new APIError(res.status, await res.text());
  return res.json();
}
