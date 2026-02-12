/** TypeScript types mirroring backend Pydantic models. */

export interface Reference {
  id: number;
  raw_text: string;
  title: string;
  authors: string[];
  year: number | null;
  doi: string | null;
  journal: string | null;
  pmid: string | null;
  source_status: "pending" | "found" | "not_found" | "api_error";
  pdf_path: string | null;
  pdf_source: "user_upload" | "open_access" | "not_available" | null;
  journal_url: string | null;
}

export interface Session {
  id: string;
  status: "created" | "running" | "paused" | "complete" | "error";
  created_at: string;
  manuscript_filename: string;
  pdf_count: number;
}

export interface MatchResult {
  reference_id: number;
  pdf_path: string | null;
  confidence: number;
  match_method: string;
  needs_user_confirmation: boolean;
  candidate_alternatives: string[];
}

export interface PipelineEvent {
  stage: number;
  status: "running" | "complete" | "error" | "needs_input" | "pipeline_complete";
  progress?: { current: number; total: number };
  message?: string;
  elapsed_seconds?: number;
  intervention?: { type: string; count?: number };
}

export interface StageStatus {
  stage: number;
  name: string;
  status: "pending" | "running" | "complete" | "error" | "needs_input";
  elapsed_seconds: number;
  progress_current: number;
  progress_total: number;
  message: string;
}

export interface ReferencesResponse {
  references: Reference[];
  total: number;
  page: number;
  per_page: number;
}

// V1: Claim types
export interface Claim {
  id: number;
  manuscript_text: string;
  extracted_claim: string;
  claim_type: "factual" | "methodological" | "background" | "attribution" | "contrast" | "interpretive";
  reference_ids: number[];
  priority: "high" | "medium" | "low";
  section_heading: string;
}

// V1: Verification types
export type Verdict = "supported" | "partially_supported" | "not_supported" | "contradicted" | "cannot_verify";

export interface ClaimDetail {
  manuscript_text: string;
  extracted_claim: string;
  claim_type: string;
  priority: string;
}

export interface VerificationResult {
  claim_id: number;
  reference_id: number;
  verdict: Verdict;
  confidence: number;
  evidence_quotes: string[];
  reasoning: string;
  tier: number;
  source_coverage: string;
  needs_user_review: boolean;
  claim: ClaimDetail;
}

export interface ResultsSummary {
  total: number;
  supported: number;
  partially_supported: number;
  not_supported: number;
  contradicted: number;
  cannot_verify: number;
}

export interface ResultsResponse {
  summary: ResultsSummary;
  results: VerificationResult[];
  total: number;
  page: number;
  per_page: number;
}
