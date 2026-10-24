/** Verdict color constants with dark mode variants. */

export const VERDICT_COLORS = {
  supported: {
    dot: "bg-green-500",
    dotDark: "bg-green-400",
    text: "text-green-700 dark:text-green-300",
    border: "border-green-500",
    bg: "bg-green-500/15",
  },
  partially_supported: {
    dot: "bg-amber-500",
    dotDark: "bg-amber-400",
    text: "text-amber-700 dark:text-amber-300",
    border: "border-amber-500",
    bg: "bg-amber-500/15",
  },
  not_supported: {
    dot: "bg-red-500",
    dotDark: "bg-red-400",
    text: "text-red-700 dark:text-red-300",
    border: "border-red-500",
    bg: "bg-red-500/15",
  },
  contradicted: {
    dot: "bg-red-700",
    dotDark: "bg-red-500",
    text: "text-red-800 dark:text-red-300",
    border: "border-red-700",
    bg: "bg-red-700/15",
  },
  cannot_verify: {
    dot: "bg-gray-400",
    dotDark: "bg-gray-500",
    text: "text-gray-600 dark:text-gray-400",
    border: "border-gray-400",
    bg: "bg-gray-400/15",
  },
} as const;

export type VerdictKey = keyof typeof VERDICT_COLORS;

export function getVerdictColor(verdict: string): (typeof VERDICT_COLORS)[VerdictKey] {
  return VERDICT_COLORS[verdict as VerdictKey] ?? VERDICT_COLORS.cannot_verify;
}

export const TIER_LABELS: Record<number, string> = {
  0: "Fast",
  1: "Standard",
  2: "Premium",
  3: "Frontier",
};

export const CONSENSUS_LABELS: Record<string, string> = {
  unanimous: "Unanimous",
  supermajority: "Strong Majority",
  majority: "Majority",
  tiebreaker: "Tiebreaker",
  // V5.1 cascade: a negative verifier verdict is cross-checked by another model family
  confirmed: "Confirmed by 2 model families",
  disputed: "Disputed — needs review",
  verifier_unconfirmed: "Unconfirmed — needs review",
  // V5.5: the element check cleared some or all elements of a partial verdict
  adjudicated: "Element check",
  // V5.6: a deterministic rule (number / lineage) turned a supported verdict into a partial
  rule: "Rule check",
};

export const CONSENSUS_STYLES: Record<string, string> = {
  unanimous: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  supermajority: "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-400",
  majority: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  tiebreaker: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  confirmed: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  disputed: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  verifier_unconfirmed: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  adjudicated: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300",
  rule: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
};
