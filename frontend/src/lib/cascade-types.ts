/** V5 cascade (screen -> verifier -> judge) and LLM role-health types. */

/** V5 cascade layer; "" for results stored before V5. */
export type CascadeLayer =
  | "screen" | "verifier" | "verifier_expanded" | "verifier_recheck" | "judge" | "confirm"
  | "adjudicate" | "adjudicate_cocited" | "adjudicate_slots" | "slot_probe" | "post_rules"
  | "";
export type DecidedBy = "screen" | "verifier" | "judge" | "none";
/** V5.1: negatives are cross-checked by a second model family (see results_trace.py). */
export type ConfirmationStatus = "confirmed" | "disputed" | "unconfirmed" | "same_family" | "none";

// V5: LLM role health (/api/health)
export type LLMRole =
  | "screen" | "verifier" | "judge" | "confirm" | "adjudicator" | "utility" | "embedding";

export interface RoleHealth {
  role: LLMRole;
  model_id: string | null;
  display_name: string | null;
  provider: string | null;
  reasoning_effort: string | null;
  available: boolean;
  enabled: boolean;
  last_error: string | null;
  fallback_index: number;
  candidates: string[];
  probed: boolean;
  probe_ok: boolean | null;
  latency_ms: number | null;
  checked_at: number | null;
  // V5.8 degraded mode (only the verifier is required)
  degraded?: boolean;
  degraded_mode?: "fallback" | "skipped" | "bm25_only" | "unavailable" | null;
  /** billing = no credits / quota; auth / no_key = key problem; network / rate_limit = transient */
  cause?: string | null;
  persistent?: boolean;
  effect?: string | null;
  action?: string | null;
}

export interface HealthResponse {
  status: string;
  grobid: string;
  database: string;
  version: string;
  llm: "ok" | "degraded" | "unavailable" | "unknown";
  decisions_api: "available" | "unavailable" | "disabled" | "unknown";
  privacy_profile: string;
  deep: boolean;
  models: Partial<Record<LLMRole, RoleHealth>>;
  degraded_notices?: string[];
  actions?: string[];
}

// V5: reference PDF upload
export interface UploadPdfResponse {
  reference_id: number;
  pdf_matched: boolean;
  pdf_source: string | null;
  identity_status: "verified" | "unverified" | "mismatch";
  claims_to_reverify: number[];
  reverification_started: boolean;
  message: string;
}
