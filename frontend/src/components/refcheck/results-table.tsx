"use client";

import { useState } from "react";
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
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-16">Ref</TableHead>
          <TableHead>Claim</TableHead>
          <TableHead className="w-32">Verdict</TableHead>
          <TableHead className="w-20">Tier</TableHead>
          <TableHead className="w-24">Confidence</TableHead>
          <TableHead className="w-20">Priority</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {results.map((result) => {
          const rowKey = `${result.claim_id}-${result.reference_id}`;
          const isExpanded = expandedId === rowKey;
          return (
            <TableRow
              key={rowKey}
              className="cursor-pointer"
              onClick={() => setExpandedId(isExpanded ? null : rowKey)}
            >
              <TableCell className="font-mono text-xs">[{result.reference_id}]</TableCell>
              <TableCell>
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-sm truncate max-w-md">
                      {result.claim.extracted_claim || `Claim ${result.claim_id}`}
                    </p>
                    {result.needs_user_review && (
                      <Badge className="bg-amber-500 text-white text-[10px] px-1.5 py-0">
                        Needs Review
                      </Badge>
                    )}
                    {result.user_override && (
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-blue-400 text-blue-600">
                        Overridden
                      </Badge>
                    )}
                  </div>
                  {isExpanded && (
                    <div className="mt-3">
                      <ClaimReviewCard result={result} />
                    </div>
                  )}
                </div>
              </TableCell>
              <TableCell>
                <VerificationBadge verdict={result.verdict as Verdict} />
              </TableCell>
              <TableCell>
                <Badge variant="outline" className={TIER_COLORS[result.tier] || TIER_COLORS[1]}>
                  T{result.tier}
                </Badge>
              </TableCell>
              <TableCell className="font-mono text-sm">
                {(result.confidence * 100).toFixed(0)}%
              </TableCell>
              <TableCell>
                <PriorityBadge priority={result.claim.priority || "medium"} />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
