/** Claim and verification-result types (backend: models/claim.py, models/verification.py). */

import type { CascadeLayer, ConfirmationStatus, DecidedBy } from "./cascade-types";
import type { PartialFields, PartialSummary } from "./partial-types";
import type { ClaimQuality, ResultSignals } from "./signal-types";

// V1: Claim types
export interface Claim {
  id: number;
  manuscript_text: string;
  extracted_claim: string;
  claim_type: "factual" | "methodological" | "background" | "attribution" | "contrast" | "interpretive";
  reference_ids: number[];
  priority: "high" | "medium" | "low";
  section_heading: string;
  co_cited_count?: number;
  // V5.2: clause this reference is cited for (equals extracted_claim when it covers it all)
  cited_for?: string;
  claim_quality?: ClaimQuality;
  mapping_ambiguous?: boolean;
  candidate_reference_ids?: number[];
}

// V1: Verification types
export type Verdict = "supported" | "partially_supported" | "not_supported" | "contradicted" | "cannot_verify" | "not_relevant";

export interface ClaimDetail {
  manuscript_text: string;
  extracted_claim: string;
  claim_type: string;
  priority: string;
  // V5.2 ("" cited_for = the reference covers the whole sentence)
  cited_for?: string;
  claim_quality?: string;
  mapping_ambiguous?: boolean;
  candidate_reference_ids?: number[];
  mapping_note?: string;
  citation_markers?: string[];
}

export interface ModelReasoning {
  layer?: CascadeLayer;
  model_name: string;
  model_display: string;
  verdict: string;
  confidence: number;
  reasoning: string;
  evidence_quotes: string[];
  source_section_preview: string;
  response_time_ms: number;
  input_tokens: number;
  output_tokens: number;
}

export interface CannotVerifyBreakdown {
  total: number;
  reasons: Record<string, { count: number; claim_ids: number[] }>;
}

/** V5.4 partial sub-type fields come from PartialFields (lib/partial-types.ts). */
export interface VerificationResult extends PartialFields {
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
  // V4: Multi-model voting fields
  consensus_type?: string;
  final_tier?: number;
  total_models_consulted?: number;
  agreement_ratio?: number;
  // V2: Quality & transparency fields
  model_reasoning?: ModelReasoning[];
  cannot_verify_reason?: string | null;
  section_relevance?: string;
  text_quality_score?: number;
  // V5: screen -> verifier -> judge cascade trace
  decided_by?: DecidedBy;
  screen_p_support?: number | null;
  screen_p_problem?: number | null;
  screen_p_contradict?: number | null;
  screen_p_topic?: number | null;
  layer_path?: string[];
  escalation_path?: number[];
  votes?: { model_name: string; abbreviation: string; tier: number; verdict: string; confidence: number }[];
  cost_usd?: number;
  latency_ms?: number;
  quotes_validated?: boolean | null;
  confirmation?: ConfirmationStatus;
  confirmation_label?: string;
  // V5.2: dispute views, secondary citation, numbers not in source, unusable PDF
  signals?: ResultSignals;
}

export interface AtomicVerification {
  atom: string;
  verified: boolean | null;
  evidence: string | null;
}

/** V5.4 per-type / per-guard counts come from PartialSummary (lib/partial-types.ts). */
export interface ResultsSummary extends PartialSummary {
  total: number;
  supported: number;
  partially_supported: number;
  not_supported: number;
  contradicted: number;
  cannot_verify: number;
  not_relevant: number;
  // V5
  decided_by?: Partial<Record<DecidedBy, number>>;
  needs_review?: number;
  total_cost_usd?: number;
  // V5.8: LLM roles that ran degraded (one sentence each), then each fix once; [] = normal run
  degraded_notices?: string[];
}

export interface ResultsResponse {
  summary: ResultsSummary;
  results: VerificationResult[];
  total: number;
  page: number;
  per_page: number;
}
