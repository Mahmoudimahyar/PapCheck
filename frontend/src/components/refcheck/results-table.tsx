"use client";

import { useState } from "react";
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
                  <p className="text-sm truncate max-w-md">
                    {result.claim.extracted_claim || `Claim ${result.claim_id}`}
                  </p>
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
