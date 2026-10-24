/**
 * V5.2 citation and source signals (backend: stages/generate_report/claim_signals.py,
 * result_signals.py, source_issues.py).
 */

export type ClaimQuality = "ok" | "fragment";
export type SourceProblem = "reference_mismatch" | "pdf_scanned" | "pdf_supplement" | "pdf_metadata_only";

/** One model's verdict and its own explanation. */
export interface LayerView {
  verdict: string;
  model_name: string;
  explanation: string;
}

/** Both sides when the verifier and the blind cross-check disagreed. */
export interface DisputeViews {
  verifier: LayerView;
  cross_check: LayerView;
  shown_verdict: string;
}

export interface ResultSignals {
  dispute: DisputeViews | null;
  /** The supporting passage itself cites other work: cite the primary study. */
  secondary_citation: boolean;
  /** Claim figures found nowhere in the source text. */
  numbers_not_found: string[];
  /** The attached PDF could not stand for the cited article. */
  source_problem: SourceProblem | null;
  source_problem_text: string;
  /** V5.7: why a "supported" verdict should be checked first (possible missed problem). */
  check_first_reasons?: string[];
}

export interface ClaimSignals {
  /** Clause this reference is cited for; "" = the whole sentence. */
  cited_for: string;
  fragment: boolean;
  mapping_ambiguous: boolean;
  candidate_reference_ids: number[];
  mapping_text: string;
}

export type SourceIssueKind =
  | "retracted"
  | "wrong_pdf"
  | "scanned_pdf"
  | "supplement_pdf"
  | "metadata_only_pdf"
  | "replaced_pdf"
  | "duplicate"
  | "ambiguous_citation"
  | "title_fixed";

export interface SourceIssue {
  kind: SourceIssueKind;
  reference_ids: number[];
  claim_ids: number[];
  message: string;
}

export interface SourceIssuesResponse {
  issues: SourceIssue[];
  labels: Partial<Record<SourceIssueKind, string>>;
}
