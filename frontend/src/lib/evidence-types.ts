/** V2 evidence mapping, manuscript viewer and V4 voting types. */

import type { PartialFields } from "./partial-types";
import type { ClaimSignals, ResultSignals } from "./signal-types";

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
  consensus_type?: string;
  final_tier?: number;
  model_count?: number;
  agreeing_count?: number;
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

export interface VerificationEvidence extends PartialFields {
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
  signals?: ResultSignals;
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
    signals?: ClaimSignals;
  };
  verifications: VerificationEvidence[];
  voting_record?: VotingRecord;
}

// V4: Multi-model voting types
export interface ModelVote {
  model_name: string;
  abbreviation: string;
  tier: number;
  verdict: string;
  confidence: number;
  reasoning: string;
  evidence_quotes: string[];
  response_time_ms: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface VotingRecord {
  votes: ModelVote[];
  consensus_type: string;
  final_tier: number;
  escalation_path: number[];
  agreement_ratio: number;
  total_models_consulted: number;
}
