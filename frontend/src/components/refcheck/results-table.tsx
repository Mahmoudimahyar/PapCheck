"use client";

import { Fragment, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { VerificationBadge, PriorityBadge } from "@/components/refcheck/verification-badge";
import { ClaimReviewCard } from "@/components/refcheck/claim-review-card";
import { SignalBadges } from "@/components/refcheck/result-signals";
import { PartialTypeBadge } from "@/components/refcheck/partial-finding";
import {
  ConfirmationBadge,
  DecidedByBadge,
  ScreenRisk,
} from "@/components/refcheck/decided-by-badge";
import type { VerificationResult, Verdict } from "@/lib/types";

interface ResultsTableProps {
  results: VerificationResult[];
}

const TIER_COLORS: Record<number, string> = {
  1: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  2: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  3: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200",
};

export function ResultsTable({ results }: ResultsTableProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (results.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No results match the current filters
      </div>
    );
  }

  return (
    // @container lets the phone detail row size itself to the visible (scrolling) table width.
    <div className="@container">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-16">Ref</TableHead>
            <TableHead>Claim</TableHead>
            <TableHead className="w-32">Verdict</TableHead>
            <TableHead className="w-28">Decided by</TableHead>
            <TableHead className="w-24">Confidence</TableHead>
            <TableHead className="w-20">Priority</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {results.map((result) => {
            const rowKey = `${result.claim_id}-${result.reference_id}`;
            const isExpanded = expandedId === rowKey;
            return (
              <Fragment key={rowKey}>
                <TableRow
                  className="cursor-pointer"
                  onClick={() => setExpandedId(isExpanded ? null : rowKey)}
                >
                  <TableCell className="font-mono text-xs">[{result.reference_id}]</TableCell>
                  <TableCell>
                    <div>
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <p className="text-sm truncate max-w-md" title={result.claim.manuscript_text}>
                          {/* A narrowed clause is what this reference was checked for */}
                          {result.claim.cited_for || result.claim.extracted_claim || `Claim ${result.claim_id}`}
                        </p>
                        {result.needs_user_review && (
                          <Badge className="bg-amber-700 text-white text-[10px] px-1.5 py-0">
                            Needs Review
                          </Badge>
                        )}
                        <ConfirmationBadge
                          status={result.confirmation}
                          label={result.confirmation_label}
                          compact
                        />
                        <PartialTypeBadge verdict={result.verdict} fields={result} />
                        <SignalBadges claim={result.claim} signals={result.signals} />
                        {result.user_override && (
                          <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-blue-400 text-blue-600 dark:text-blue-400">
                            Overridden
                          </Badge>
                        )}
                        {result.verdict === "cannot_verify" && result.cannot_verify_reason && (
                          <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-orange-300 text-orange-700 dark:text-orange-400">
                            {result.cannot_verify_reason.replace(/_/g, " ")}
                          </Badge>
                        )}
                      </div>
                      {isExpanded && (
                        // Clicks inside the card (e.g. opening the layer trace) must not collapse the row;
                        // whitespace-normal undoes TableCell's nowrap so the card's text wraps.
                        <div className="mt-3 whitespace-normal hidden sm:block" onClick={(e) => e.stopPropagation()}>
                          <ClaimReviewCard result={result} />
                        </div>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <VerificationBadge verdict={result.verdict as Verdict} />
                  </TableCell>
                  <TableCell>
                    {result.decided_by && result.decided_by !== "none" ? (
                      <div className="flex flex-col items-start gap-0.5">
                        <DecidedByBadge decidedBy={result.decided_by} className="text-[10px] px-1.5 py-0" />
                        <ScreenRisk pProblem={result.screen_p_problem} className="text-[10px]" />
                      </div>
                    ) : (
                      <Badge variant="outline" className={TIER_COLORS[result.tier] || TIER_COLORS[1]}>
                        T{result.tier}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-sm">
                    {(result.confidence * 100).toFixed(0)}%
                  </TableCell>
                  <TableCell>
                    <PriorityBadge priority={result.claim.priority || "medium"} />
                  </TableCell>
                </TableRow>
                {isExpanded && (
                  // Phones: the detail gets its own row, pinned to the visible width of the scrolling table.
                  <TableRow className="sm:hidden hover:bg-transparent">
                    <TableCell colSpan={6} className="p-0 whitespace-normal">
                      <div className="sticky left-0 w-[100cqw] p-2">
                        <ClaimReviewCard result={result} />
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
