"use client";

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
