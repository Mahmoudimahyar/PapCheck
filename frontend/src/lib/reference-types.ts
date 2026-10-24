/** Reference, PDF match and library types (backend: models/reference.py, library/). */

export interface Reference {
  id: number;
  raw_text: string;
  title: string;
  authors: string[];
  year: number | null;
  doi: string | null;
  journal: string | null;
  pmid: string | null;
  pmc_id: string | null;
  source_status: "pending" | "found" | "not_found" | "api_error";
  pdf_path: string | null;
  pdf_source: "user_upload" | "open_access" | "library" | "not_available" | null;
  journal_url: string | null;
  retraction_status: "ok" | "retracted" | "corrected" | "expression_of_concern" | "unknown";
  retraction_detail: string;
  duplicate_of: number | null;
  is_supplementary: boolean;
  // V2 fields
  raw_text_original: string;
  repair_applied: string;
  reference_type: string;
  abstract_text: string | null;
  abstract_source: string | null;
  // V5: does the attached PDF belong to this reference?
  identity_status?: "verified" | "unverified" | "mismatch";
  // V5.2: author-year letter, "(2018b)" -> "b"
  year_suffix?: string | null;
  // V5.8 G3: why the uploaded PDF was replaced by a library / open-access copy
  replaced_upload_reason?: string | null;
  // V5.9: where a free legal copy lives (Unpaywall / OpenAlex); undefined = not checked yet
  oa_status?: OaStatus | null;
  oa_url?: string | null;
  oa_pdf_url?: string | null;
  /** e.g. "cc-by", "cc-by-nc-nd", "implied-oa" */
  oa_license?: string | null;
  /** "publishedVersion" | "acceptedVersion" | "submittedVersion" */
  oa_version?: string | null;
}

/** Unpaywall / OpenAlex open-access colour; "closed" = checked, no free copy. */
export type OaStatus = "gold" | "diamond" | "green" | "hybrid" | "bronze" | "closed";

/** Free-full-text hint (backend: models/open_access.py OpenAccessHint). */
export interface OpenAccessHint {
  oa_status: OaStatus | null;
  oa_url: string | null;
  oa_pdf_url: string | null;
  oa_license: string | null;
  oa_version: string | null;
  pmc_id: string | null;
}

/** V5.9: POST .../references/{id}/refresh-metadata (backend: services/reverifier.py). */
export interface RefreshMetadataResponse {
  reference_id: number;
  changed_fields: string[];
  abstract_changed: boolean;
  abstract_source: string | null;
  abstract_chars: number;
  previous_abstract_chars: number;
  open_access: OpenAccessHint;
  /** Re-verified in a background task when `reverification_started` (abstract changed). */
  claims_to_reverify: number[];
  reverification_started: boolean;
}

export interface ReferenceLinks {
  doi_url: string | null;
  pubmed_url: string | null;
  scholar_url: string | null;
  pmc_url: string | null;
  journal_url: string | null;
}

export interface MatchResult {
  reference_id: number;
  pdf_path: string | null;
  confidence: number;
  match_method: string;
  needs_user_confirmation: boolean;
  candidate_alternatives: string[];
}

export interface ReferencesResponse {
  references: Reference[];
  total: number;
  page: number;
  per_page: number;
}

// Library types
export interface LibraryStats {
  total: number;
  with_pdf: number;
  by_source: Record<string, number>;
}
