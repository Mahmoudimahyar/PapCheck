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
  retraction_status: "ok" | "retracted" | "corrected" | "expression_of_concern" | "unknown";
  retraction_detail: string;
  duplicate_of: number | null;
  is_supplementary: boolean;
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
  user_override: boolean;
  user_override_reason: string;
  atomic_results?: AtomicVerification[];
}

export interface AtomicVerification {
  atom: string;
  verified: boolean | null;
  evidence: string | null;
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

// V3: Session list
export interface SessionListResponse {
  sessions: Session[];
  total: number;
  page: number;
  per_page: number;
}

// V2: Evidence Mapping & Manuscript Viewer types

export interface ClaimLocation {
  paragraph_index: number;
  char_start: number;
  char_end: number;
  citation_markers: string[];
  section_heading: string;
  in_figure_or_table: boolean;
}

export interface QuoteHighlight {
  quote: string;
  char_start: number;
  char_end: number;
  match_type: "direct" | "paraphrased" | "numeric_mismatch" | "absent";
  manuscript_element: string;
}

export interface EvidenceSection {
  section_heading: string;
  full_text: string;
  page_number: number | null;
  quote_highlights: QuoteHighlight[];
}

export interface ParagraphClaim {
  claim_id: number;
  char_start: number;
  char_end: number;
  citation_markers: string[];
  verdict: string;
  confidence: number;
  reference_ids: number[];
}

export interface ManuscriptParagraph {
  index: number;
  text: string;
  section_heading: string;
  claims: ParagraphClaim[];
}

export interface ManuscriptResponse {
  title: string;
  paragraphs: ManuscriptParagraph[];
  legend: Record<string, number>;
  total_claims: number;
  total_paragraphs: number;
  unmapped_claims: number[];
}

export interface VerificationEvidence {
  reference_id: number;
  reference_title: string;
  reference_authors: string[];
  verdict: string;
  confidence: number;
  tier: number;
  reasoning: string;
  evidence_sections: EvidenceSection[];
  atomic_results: { atom: string; verified: boolean | null; evidence: string | null }[] | null;
  user_override: boolean;
  user_override_reason: string;
}

export interface EvidenceResponse {
  claim: {
    id: number;
    manuscript_text: string;
    extracted_claim: string;
    claim_type: string;
    priority: string;
    atomic_claims: string[];
    location: ClaimLocation | null;
  };
  verifications: VerificationEvidence[];
}

// V2 Report types
export interface ReportPreview {
  summary: Record<string, number>;
  critical_findings: Array<Record<string, string>>;
  minor_issues: Array<Record<string, string>>;
  retracted: Array<Record<string, string>>;
  overrides_count: number;
  generated_at: string;
}
