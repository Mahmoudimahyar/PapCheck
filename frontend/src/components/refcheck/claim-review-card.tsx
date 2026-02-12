"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { VerificationBadge } from "@/components/refcheck/verification-badge";
import type { VerificationResult } from "@/lib/types";

interface ClaimReviewCardProps {
  result: VerificationResult;
}

export function ClaimReviewCard({ result }: ClaimReviewCardProps) {
  return (
    <Card className="border-l-4 border-l-muted">
      <CardContent className="pt-4 space-y-3">
        {result.claim.manuscript_text && (
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Manuscript says</p>
            <p className="text-sm italic">&ldquo;{result.claim.manuscript_text}&rdquo;</p>
          </div>
        )}

        {result.claim.extracted_claim && (
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Claim</p>
            <p className="text-sm">{result.claim.extracted_claim}</p>
          </div>
        )}

        {result.evidence_quotes.length > 0 && (
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Source says</p>
            {result.evidence_quotes.map((quote, i) => (
              <p key={i} className="text-sm italic text-muted-foreground ml-3 border-l-2 border-muted pl-2">
                &ldquo;{quote}&rdquo;
              </p>
            ))}
          </div>
        )}

        {result.reasoning && (
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Reasoning</p>
            <p className="text-sm">{result.reasoning}</p>
          </div>
        )}

        {/* Atomic results (V2) */}
        {result.atomic_results && result.atomic_results.length > 0 && (
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Atomic Claims</p>
            <div className="space-y-1 mt-1">
              {result.atomic_results.map((atom, i) => (
                <div key={i} className="flex items-start gap-2 text-sm">
                  <Badge
                    variant="outline"
                    className={`text-[10px] px-1.5 py-0 mt-0.5 shrink-0 ${
                      atom.verified === true
                        ? "border-green-400 text-green-700"
                        : atom.verified === false
                          ? "border-red-400 text-red-700"
                          : "border-gray-300 text-gray-500"
                    }`}
                  >
                    {atom.verified === true ? "OK" : atom.verified === false ? "FAIL" : "N/A"}
                  </Badge>
                  <span>{atom.atom}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* User override info */}
        {result.user_override && (
          <div className="p-2 bg-blue-50 dark:bg-blue-950 rounded border border-blue-200 dark:border-blue-800">
            <p className="text-xs font-medium text-blue-700 dark:text-blue-300">User Override Applied</p>
            {result.user_override_reason && (
              <p className="text-xs text-blue-600 dark:text-blue-400 mt-0.5">{result.user_override_reason}</p>
            )}
          </div>
        )}

        <div className="flex items-center gap-3 text-xs text-muted-foreground pt-1 border-t">
          <span>Confidence: {(result.confidence * 100).toFixed(0)}%</span>
          <span>Tier: {result.tier}</span>
          <span>Coverage: {result.source_coverage.replace("_", " ")}</span>
          {result.needs_user_review && (
            <VerificationBadge verdict="cannot_verify" className="text-xs" />
          )}
        </div>
      </CardContent>
    </Card>
  );
}
