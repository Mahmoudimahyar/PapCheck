"use client";

import { ShieldAlert, ShieldCheck, Scale, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  CONFIRMATION_SHORT,
  CONFIRMATION_STYLES,
  DECIDED_BY_LABELS,
  DECIDED_BY_STYLES,
  formatPercent,
  pProblemTone,
} from "@/lib/cascade";
import type { ConfirmationStatus, DecidedBy } from "@/lib/types";

const LEGACY_TIER_STYLE = "bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-800 dark:text-gray-300";

/** "Decided by: Fast screen / Verifier / Judge" (falls back to the tier for pre-V5 results). */
export function DecidedByBadge({
  decidedBy,
  tier,
  withPrefix = false,
  className = "",
}: {
  decidedBy?: DecidedBy;
  tier?: number;
  withPrefix?: boolean;
  className?: string;
}) {
  if (!decidedBy || decidedBy === "none") {
    if (tier === undefined) return null;
    return (
      <Badge variant="outline" className={`${LEGACY_TIER_STYLE} ${className}`}>
        T{tier}
      </Badge>
    );
  }
  return (
    <Badge
      variant="outline"
      className={`${DECIDED_BY_STYLES[decidedBy]} ${className}`}
      title="Which layer of the screen → verifier → judge cascade made the final call"
    >
      {withPrefix ? `Decided by: ${DECIDED_BY_LABELS[decidedBy]}` : DECIDED_BY_LABELS[decidedBy]}
    </Badge>
  );
}

/** Fast-screen risk: P(problem) = 1 − P(support). */
export function ScreenRisk({ pProblem, className = "" }: { pProblem?: number | null; className?: string }) {
  if (pProblem === null || pProblem === undefined) return null;
  return (
    <span
      className={`text-xs font-mono ${pProblemTone(pProblem)} ${className}`}
      title="Fast screen estimate that the citation has a problem (1 − P(support))"
    >
      P(problem) {formatPercent(pProblem)}
    </span>
  );
}

const CONFIRMATION_ICONS: Record<ConfirmationStatus, React.ReactNode> = {
  confirmed: <ShieldCheck />,
  disputed: <Scale />,
  unconfirmed: <ShieldAlert />,
  same_family: <Users />,
  none: null,
};

/** "Confirmed by 2 model families" / "Disputed" (nothing when a single layer decided). */
export function ConfirmationBadge({
  status,
  label,
  compact = false,
}: {
  status?: ConfirmationStatus;
  label?: string;
  compact?: boolean;
}) {
  if (!status || status === "none") return null;
  return (
    <Badge
      variant="outline"
      className={`${CONFIRMATION_STYLES[status]} ${compact ? "text-[10px] px-1.5 py-0" : ""}`}
      title={label || CONFIRMATION_SHORT[status]}
    >
      {CONFIRMATION_ICONS[status]}
      {compact ? CONFIRMATION_SHORT[status] : label || CONFIRMATION_SHORT[status]}
    </Badge>
  );
}
