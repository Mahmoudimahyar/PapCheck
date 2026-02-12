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
