/** Labels and colours for the V5 screen -> verifier -> judge cascade. */

import type { ConfirmationStatus, DecidedBy, LLMRole } from "./cascade-types";

export const DECIDED_BY_LABELS: Record<DecidedBy, string> = {
  screen: "Fast screen",
  verifier: "Verifier",
  judge: "Judge",
  none: "Not decided",
};

export const DECIDED_BY_STYLES: Record<DecidedBy, string> = {
  screen: "bg-sky-100 text-sky-800 border-sky-200 dark:bg-sky-900/40 dark:text-sky-200 dark:border-sky-800",
  verifier: "bg-violet-100 text-violet-800 border-violet-200 dark:bg-violet-900/40 dark:text-violet-200 dark:border-violet-800",
  judge: "bg-indigo-100 text-indigo-800 border-indigo-200 dark:bg-indigo-900/40 dark:text-indigo-200 dark:border-indigo-800",
  none: "bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700",
};

export const LAYER_LABELS: Record<string, string> = {
  screen: "Fast screen",
  verifier: "Verifier",
  verifier_expanded: "Verifier (expanded evidence)",
  verifier_recheck: "Verifier (evidence re-check)",
  judge: "Judge",
  confirm: "Confirm",
  adjudicate: "Element check",
  adjudicate_cocited: "Element check (co-cited)",
  adjudicate_slots: "Element check (claim slots)",
  slot_probe: "Slot probe",
  post_rules: "Rule check",
};

export const ROLE_LABELS: Record<LLMRole, string> = {
  screen: "Fast screen",
  verifier: "Verifier",
  judge: "Judge",
  confirm: "Confirm",
  adjudicator: "Element check",
  utility: "Utility",
  embedding: "Embeddings",
};

const GREEN = "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200";
const AMBER = "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200";
const RED = "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
const GRAY = "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200";

/** Verdict chip colours, including the per-layer trace verdicts. */
export const TRACE_VERDICT_STYLES: Record<string, string> = {
  supported: GREEN,
  partially_supported: AMBER,
  not_supported: RED,
  contradicted: "bg-red-200 text-red-900 dark:bg-red-800 dark:text-red-100",
  not_relevant: "bg-violet-100 text-violet-800 dark:bg-violet-900 dark:text-violet-200",
  cannot_verify: GRAY,
  insufficient_evidence: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
  likely_supported: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  possible_problem: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  screen_inconclusive: "bg-sky-50 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  escalate: "bg-sky-50 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  error: "bg-red-50 text-red-700 border border-red-300 dark:bg-red-950 dark:text-red-300",
};

export function traceVerdictStyle(verdict: string): string {
  return TRACE_VERDICT_STYLES[verdict] ?? GRAY;
}

export function formatLabel(value: string): string {
  return value.replace(/_/g, " ");
}

export const CONFIRMATION_STYLES: Record<ConfirmationStatus, string> = {
  confirmed: "border-green-300 text-green-700 dark:border-green-700 dark:text-green-300",
  disputed: "border-amber-400 text-amber-700 dark:border-amber-600 dark:text-amber-300",
  unconfirmed: "border-amber-300 text-amber-700 dark:border-amber-700 dark:text-amber-300",
  same_family: "border-gray-300 text-gray-600 dark:border-gray-600 dark:text-gray-300",
  none: "",
};

export const CONFIRMATION_SHORT: Record<ConfirmationStatus, string> = {
  confirmed: "Confirmed",
  disputed: "Disputed",
  unconfirmed: "Unconfirmed",
  same_family: "Same-family agreement",
  none: "",
};

/** Colour for the screen's P(problem) = 1 - P(support). */
export function pProblemTone(p: number): string {
  if (p >= 0.5) return "text-red-600 dark:text-red-400";
  if (p >= 0.2) return "text-amber-700 dark:text-amber-400";
  return "text-green-700 dark:text-green-400";
}

export function formatPercent(p: number): string {
  return `${Math.round(p * 100)}%`;
}

export function formatUsd(usd: number): string {
  if (usd === 0) return "$0";
  return usd < 0.1 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`;
}

export function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}
