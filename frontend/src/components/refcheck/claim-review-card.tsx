"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { VerificationBadge } from "@/components/refcheck/verification-badge";
import ClaimReasoning from "@/components/refcheck/claim-reasoning";
import { DecidedByBadge, ScreenRisk } from "@/components/refcheck/decided-by-badge";
import { CitedFor, ClaimWarnings, DisputePanel, ResultNotes } from "@/components/refcheck/result-signals";
import { GuardNotes, PartialFinding } from "@/components/refcheck/partial-finding";
import { formatUsd } from "@/lib/cascade";
import type { VerificationResult } from "@/lib/types";

interface ClaimReviewCardProps {
  result: VerificationResult;
}

function formatReason(reason: string): string {
  return reason.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function ClaimReviewCard({ result }: ClaimReviewCardProps) {
  return (
    <Card className="border-l-4 border-l-muted">
      <CardContent className="pt-4 space-y-3">
        {/* Cannot-verify reason banner */}
        {result.verdict === "cannot_verify" && result.cannot_verify_reason && (
          <div className="p-2 bg-orange-50 dark:bg-orange-950 rounded border border-orange-200 dark:border-orange-800">
            <p className="text-xs font-medium text-orange-700 dark:text-orange-300">
              Why can&apos;t we verify: {formatReason(result.cannot_verify_reason)}
            </p>
          </div>
        )}

        <ClaimWarnings claim={result.claim} signals={result.signals} />

        {result.claim.manuscript_text && (
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Manuscript says</p>
            <p className="text-sm italic">&ldquo;{result.claim.manuscript_text}&rdquo;</p>
          </div>
        )}

        <CitedFor citedFor={result.claim.cited_for} />

        {result.claim.extracted_claim && !result.claim.cited_for && (
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Claim</p>
            <p className="text-sm">{result.claim.extracted_claim}</p>
          </div>
        )}

        <PartialFinding verdict={result.verdict} fields={result} />

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

        <DisputePanel dispute={result.signals?.dispute} />
        <ResultNotes signals={result.signals} />
        <GuardNotes verdict={result.verdict} guards={result.guards_applied} />

        {/* LLM Model Reasoning (V2 — per-model breakdown) */}
        {result.model_reasoning && result.model_reasoning.length > 0 && (
          <ClaimReasoning
            verdict={result.verdict}
            confidence={result.confidence}
            sourceCoverage={result.source_coverage}
            modelReasoning={result.model_reasoning}
            cannotVerifyReason={result.cannot_verify_reason}
            sectionRelevance={result.section_relevance}
            textQualityScore={result.text_quality_score}
            decidedBy={result.decided_by}
            consensusType={result.consensus_type}
            screenPProblem={result.screen_p_problem}
            confirmation={result.confirmation}
            confirmationLabel={result.confirmation_label}
            costUsd={result.cost_usd}
            latencyMs={result.latency_ms}
            quotesValidated={result.quotes_validated}
          />
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
                        ? "border-green-400 text-green-700 dark:text-green-400"
                        : atom.verified === false
                          ? "border-red-400 text-red-700 dark:text-red-400"
                          : "border-gray-300 text-gray-500 dark:text-gray-400"
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

        <div className="flex items-center gap-3 text-xs text-muted-foreground pt-1 border-t flex-wrap">
          <span>Confidence: {(result.confidence * 100).toFixed(0)}%</span>
          {result.decided_by && result.decided_by !== "none" ? (
            <span className="flex items-center gap-1">
              Decided by: <DecidedByBadge decidedBy={result.decided_by} className="text-[10px] px-1.5 py-0" />
            </span>
          ) : (
            <span>Tier: {result.tier}</span>
          )}
          <ScreenRisk pProblem={result.screen_p_problem} />
          {result.cost_usd !== undefined && result.cost_usd > 0 && (
            <span>Cost: {formatUsd(result.cost_usd)}</span>
          )}
          <span>Coverage: {result.source_coverage.replace(/_/g, " ")}</span>
          {result.needs_user_review && (
            <VerificationBadge verdict="cannot_verify" className="text-xs" />
          )}
        </div>
      </CardContent>
    </Card>
  );
}
