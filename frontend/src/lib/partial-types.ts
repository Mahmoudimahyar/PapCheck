/**
 * V5.4 partial-verdict sub-types (taxonomy v1.1).
 *
 * Labels, meanings, severities and guard notes are COPIED from the Python source of truth
 * `src/refcheck/models/partial_types.py` (PARTIAL_TYPE_INFO, GUARD_LABELS) and the
 * "unclassified" bucket from `src/refcheck/stages/generate_report/partial_findings.py`.
 * tests/unit/test_partial_types_ts_sync.py fails when they drift apart.
 */

export type PartialSeverity = "minor" | "major";

export type PartialTypeId =
  | "specific_detail_mismatch"
  | "tangential_source"
  | "unsupported_inference"
  | "scope_overgeneralized"
  | "missing_element"
  | "certainty_overstated"
  | "coverage_limited";

/** A partial type, or "unclassified" for partial results without a recorded type. */
export type PartialTypeKey = PartialTypeId | "unclassified";

export type GuardName =
  | "evidence_recheck"
  | "cocited_share"
  | "author_framing_or_example"
  | "overliteral_wording";

export interface PartialTypeInfo {
  label: string;
  meaning: string;
  severity: PartialSeverity;
}

/** Report / UI sub-section order (taxonomy report_subsections). */
export const PARTIAL_TYPE_INFO: Record<PartialTypeKey, PartialTypeInfo> = {
  specific_detail_mismatch: {
    label: "Wrong or missing specifics",
    meaning: "A number, model, material or other specific is absent from or different in the source.",
    severity: "major",
  },
  tangential_source: {
    label: "Weak or misplaced citation",
    meaning: "The source does not support the main point of the clause the citation is attached to.",
    severity: "major",
  },
  unsupported_inference: {
    label: "Author's inference attributed to the source",
    meaning: "The facts are in the source, but the link, cause or conclusion drawn from them is not.",
    severity: "major",
  },
  scope_overgeneralized: {
    label: "Overgeneralized scope",
    meaning: "A result is stretched beyond the source's population, model or breadth.",
    severity: "major",
  },
  missing_element: {
    label: "Missing pieces",
    meaning: "Part of a compound claim has no support in this source.",
    severity: "minor",
  },
  certainty_overstated: {
    label: "Overstated certainty",
    meaning: "The source says the same thing with more caution, or weaker results.",
    severity: "minor",
  },
  coverage_limited: {
    label: "Could not verify (coverage)",
    meaning: "Only the abstract or part of the paper was available, so part of the claim could not be checked.",
    severity: "minor",
  },
  unclassified: {
    label: "Other partial findings",
    meaning: "Partial results without a recorded type (older runs or reviewer overrides).",
    severity: "minor",
  },
};

export const PARTIAL_TYPE_ORDER = Object.keys(PARTIAL_TYPE_INFO) as PartialTypeKey[];

/** Note shown on a supported result when a benign guard cleared a concern. */
export const GUARD_LABELS: Record<GuardName, { label: string; explanation: string }> = {
  evidence_recheck: {
    label: "Evidence re-check",
    explanation: "A targeted search of the full text found the passage the first check missed.",
  },
  cocited_share: {
    label: "Co-cited reference",
    explanation:
      "The rest of the sentence is supported by the other reference(s) cited with it; " +
      "consider placing each citation next to the clause it supports.",
  },
  author_framing_or_example: {
    label: "Author framing / example",
    explanation: "The source is cited as an example, or the extra words are the author's own framing.",
  },
  overliteral_wording: {
    label: "Wording only",
    explanation: "The claim paraphrases the source; the difference is wording, not substance.",
  },
};

export const GUARD_ORDER = Object.keys(GUARD_LABELS) as GuardName[];

/** Results-API `partial_type` filter values: a type key, "guarded" or "guarded:<guard>". */
export type PartialFilter = "all" | PartialTypeKey | "guarded" | `guarded:${GuardName}`;

/** V5.4 fields on a result (results API item and evidence endpoint). */
export interface PartialFields {
  partial_type?: string | null;
  partial_severity?: PartialSeverity | null;
  author_action?: string;
  unsupported_elements?: string[];
  guards_applied?: string[];
}

/** V5.4 summary counts on the results API. */
export interface PartialSummary {
  partial_types?: Partial<Record<PartialTypeKey, number>>;
  partial_severity?: Partial<Record<PartialSeverity, number>>;
  guarded?: number;
  guards?: Partial<Record<GuardName, number>>;
}

export function isPartialTypeKey(value: string | null | undefined): value is PartialTypeKey {
  return !!value && value in PARTIAL_TYPE_INFO;
}

export function isGuardName(value: string): value is GuardName {
  return value in GUARD_LABELS;
}

/** Type info for a stored partial_type ("unclassified" excluded: it has no stored id). */
export function partialTypeInfo(partialType: string | null | undefined): PartialTypeInfo | null {
  if (!isPartialTypeKey(partialType) || partialType === "unclassified") return null;
  return PARTIAL_TYPE_INFO[partialType];
}

/** Known guards that cleared a concern, in taxonomy order. */
export function knownGuards(guards: string[] | undefined): GuardName[] {
  return GUARD_ORDER.filter((g) => guards?.includes(g));
}

/** Human label for a filter value (chips and the active-filter note). */
export function partialFilterLabel(filter: PartialFilter): string {
  if (filter === "all") return "All";
  if (filter === "guarded") return "Supported with a note";
  if (filter.startsWith("guarded:")) {
    const guard = filter.slice("guarded:".length);
    return isGuardName(guard) ? `Cleared: ${GUARD_LABELS[guard].label}` : filter;
  }
  return isPartialTypeKey(filter) ? PARTIAL_TYPE_INFO[filter].label : filter;
}

/** GET /api/sessions/{id}/partial-breakdown (backend: api/routes/partial_breakdown.py). */
export interface PartialTypeDetail {
  type: PartialTypeKey;
  label: string;
  meaning: string;
  severity: PartialSeverity;
  count: number;
  major: number;
  minor: number;
  author_action: string;
  claim_ids: number[];
}

export interface GuardDetail {
  guard: GuardName;
  label: string;
  explanation: string;
  count: number;
  claim_ids: number[];
}

export interface PartialBreakdown {
  total_partial: number;
  types: PartialTypeDetail[];
  guarded: number;
  guards: GuardDetail[];
}

/** Both filters can hold for one result (a guard filter implies supported, a type partial). */
function filtersAgree(filter: PartialFilter, verdictFilter: string): boolean {
  if (filter === "all" || verdictFilter === "all" || verdictFilter === "needs_review") return true;
  const guarded = filter === "guarded" || filter.startsWith("guarded:");
  return verdictFilter === (guarded ? "supported" : "partially_supported");
}

/** The verdict filter to keep when a partial filter is chosen ("all" when they conflict). */
export function compatibleVerdictFilter(filter: PartialFilter, verdictFilter: string): string {
  return filtersAgree(filter, verdictFilter) ? verdictFilter : "all";
}

/** The partial filter to keep when a verdict filter is chosen ("all" when they conflict). */
export function compatiblePartialFilter(verdictFilter: string, filter: PartialFilter): PartialFilter {
  return filtersAgree(filter, verdictFilter) ? filter : "all";
}
