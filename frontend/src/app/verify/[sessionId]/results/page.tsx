"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ResultsChart } from "@/components/refcheck/results-chart";
import { ResultsTable } from "@/components/refcheck/results-table";
import { HumanReviewModal } from "@/components/refcheck/human-review-modal";
import { ResultsFilterBar } from "@/components/refcheck/results-filter-bar";
import { CostFromResults, ResultsLoadingSkeleton, SummaryCard } from "@/components/refcheck/results-helpers";
import { DegradedRunBanner } from "@/components/refcheck/degraded-run-banner";
import CannotVerifyBreakdownPanel from "@/components/refcheck/cannot-verify-breakdown";
import { PartialTypeBreakdown } from "@/components/refcheck/partial-type-breakdown";
import { BreadcrumbNav } from "@/components/refcheck/breadcrumb-nav";
import { getAllResults, getResults, getReportUrl, getCannotVerifyBreakdown, getPartialBreakdown, overrideVerdict } from "@/lib/api";
import { compatiblePartialFilter, compatibleVerdictFilter, type PartialBreakdown, type PartialFilter } from "@/lib/partial-types";
import type { CannotVerifyBreakdown, ResultsResponse, ResultsSummary, Verdict, VerificationResult } from "@/lib/types";

const EMPTY_SUMMARY: ResultsSummary = {
  total: 0, supported: 0, partially_supported: 0,
  not_supported: 0, contradicted: 0, cannot_verify: 0, not_relevant: 0,
};

export default function ResultsPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);
  const [summary, setSummary] = useState<ResultsSummary>(EMPTY_SUMMARY);
  const [results, setResults] = useState<VerificationResult[]>([]);
  const [verdictFilter, setVerdictFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [partialFilter, setPartialFilter] = useState<PartialFilter>("all");
  const [partialBreakdown, setPartialBreakdown] = useState<PartialBreakdown | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewIndex, setReviewIndex] = useState(0);
  const [breakdown, setBreakdown] = useState<CannotVerifyBreakdown | null>(null);

  const fetchResults = useCallback(async () => {
    try {
      setLoading(true); setError(null);
      const filters: { verdict?: string; priority?: string; partial_type?: string } = {};
      if (verdictFilter !== "all" && verdictFilter !== "needs_review") filters.verdict = verdictFilter;
      if (priorityFilter !== "all") filters.priority = priorityFilter;
      if (partialFilter !== "all") filters.partial_type = partialFilter;
      // Every page: the API caps a page at 200 rows; manuscripts often have more pairs.
      const data: ResultsResponse = await getAllResults(sessionId, filters);
      setSummary(data.summary);
      setResults(verdictFilter === "needs_review"
        ? data.results.filter((r) => r.needs_user_review)
        : data.results);
      if (data.summary.cannot_verify > 0) {
        try { setBreakdown(await getCannotVerifyBreakdown(sessionId)); } catch { /* optional */ }
      } else setBreakdown(null); // a re-verification can clear the last cannot_verify
    } catch { setError("Failed to load results."); }
    finally { setLoading(false); }
  }, [sessionId, verdictFilter, priorityFilter, partialFilter]);

  useEffect(() => { fetchResults(); }, [fetchResults]);
  const fetchPartialBreakdown = useCallback(() => {
    getPartialBreakdown(sessionId).then(setPartialBreakdown).catch(() => { /* optional section */ });
  }, [sessionId]);
  useEffect(() => { fetchPartialBreakdown(); }, [fetchPartialBreakdown]);
  // A metadata refresh re-verified a reference's claims in the background: reload what is shown.
  const reloadAfterReverify = useCallback(() => { void fetchResults(); fetchPartialBreakdown(); },
    [fetchResults, fetchPartialBreakdown]);

  // An override moves a result between verdicts and partial types: refresh the counts.
  const refreshCounts = useCallback(async () => {
    try { setSummary((await getResults(sessionId, { page: 1, per_page: 1 })).summary); }
    catch { /* keep the previous counts */ }
    fetchPartialBreakdown();
  }, [sessionId, fetchPartialBreakdown]);

  // A partial-type filter implies a verdict; drop a verdict filter that contradicts it.
  const selectPartial = (value: PartialFilter, scroll = false) => {
    setPartialFilter(value);
    setVerdictFilter((v) => compatibleVerdictFilter(value, v));
    if (scroll) document.getElementById("results-filters")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  // ...and a verdict filter drops a partial filter that contradicts it (else the table is empty).
  const selectVerdict = (value: string) => {
    setVerdictFilter(value);
    setPartialFilter((p) => compatiblePartialFilter(value, p));
  };

  const reviewable = useMemo(() => results.filter((r) => r.needs_user_review && !r.user_override), [results]);
  const needsReviewCount = useMemo(() => results.filter((r) => r.needs_user_review).length, [results]);
  const current = reviewable.length > 0 && reviewIndex < reviewable.length ? reviewable[reviewIndex] : null;

  const handleSubmit = async (verdict: Verdict, reason: string) => {
    if (!current) return;
    try {
      const u = await overrideVerdict(sessionId, current.claim_id, verdict, reason);
      setResults((p) => p.map((r) => r.claim_id === u.claim_id && r.reference_id === u.reference_id ? u : r));
      // The reviewed result leaves `reviewable`, so the next one moves up to the same index.
      if (reviewIndex + 1 >= reviewable.length) setReviewOpen(false);
      refreshCounts();
    } catch { /* user can retry */ }
  };

  const handleSkip = () => {
    if (reviewIndex + 1 < reviewable.length) setReviewIndex((i) => i + 1); else setReviewOpen(false);
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <BreadcrumbNav sessionId={sessionId} current="results" />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-2xl font-semibold">Verification Results</h2>
        <div className="flex flex-wrap gap-2">
          <Link href={`/verify/${sessionId}/viewer`}><Button variant="outline" size="sm">Manuscript View</Button></Link>
          <Link href={`/verify/${sessionId}/report`}><Button variant="outline" size="sm">View Report</Button></Link>
          <a href={getReportUrl(sessionId)} download><Button size="sm">Download Report</Button></a>
        </div>
      </div>

      <DegradedRunBanner notices={summary.degraded_notices} />

      {error && <div className="text-sm text-destructive p-4 border border-destructive/30 rounded">{error}</div>}

      {needsReviewCount > 0 && (
        <Card className="border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950">
          <CardContent className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div className="flex min-w-0 items-center gap-3">
              <Badge className="bg-amber-700 text-white">{reviewable.length} pending</Badge>
              <span className="text-sm text-amber-950 dark:text-amber-50">
                {needsReviewCount} result{needsReviewCount > 1 ? "s" : ""} flagged for human review
              </span>
            </div>
            {reviewable.length > 0 && <Button size="sm" onClick={() => { setReviewIndex(0); setReviewOpen(true); }}>Start Review</Button>}
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <SummaryCard label="Supported" count={summary.supported} color="text-green-600 dark:text-green-400" bg="bg-green-50 dark:bg-green-950" />
        <SummaryCard label="Partial" count={summary.partially_supported} color="text-amber-600 dark:text-amber-400" bg="bg-amber-50 dark:bg-amber-950" />
        <SummaryCard label="Not Supported" count={summary.not_supported} color="text-red-600 dark:text-red-400" bg="bg-red-50 dark:bg-red-950" />
        <SummaryCard label="Contradicted" count={summary.contradicted} color="text-red-800 dark:text-red-300" bg="bg-red-100 dark:bg-red-900/40" />
        <SummaryCard label="Can't Verify" count={summary.cannot_verify} color="text-gray-500 dark:text-gray-400" bg="bg-gray-50 dark:bg-gray-900" />
        <SummaryCard label="Not Relevant" count={summary.not_relevant ?? 0} color="text-violet-600 dark:text-violet-400" bg="bg-violet-50 dark:bg-violet-950" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="md:col-span-2">
          <CardHeader><h3 className="text-lg font-medium">Verdict Distribution</h3></CardHeader>
          <CardContent><ResultsChart summary={summary} /></CardContent>
        </Card>
        <CostFromResults results={results} />
      </div>

      {breakdown && breakdown.total > 0 && (
        <CannotVerifyBreakdownPanel
          breakdown={breakdown}
          sessionId={sessionId}
          onResultsChanged={reloadAfterReverify}
          onUploadClick={() => window.location.href = `/verify/${sessionId}/review`}
        />
      )}

      {partialBreakdown && (
        <PartialTypeBreakdown
          breakdown={partialBreakdown} activeFilter={partialFilter}
          onSelect={(value) => selectPartial(value, true)}
        />
      )}

      <div id="results-filters" className="scroll-mt-4">
        <ResultsFilterBar
          verdictFilter={verdictFilter} priorityFilter={priorityFilter}
          onVerdictChange={selectVerdict} onPriorityChange={setPriorityFilter}
          resultCount={results.length} totalCount={summary.total} loading={loading}
          partialFilter={partialFilter} onPartialChange={(value) => selectPartial(value)}
          partialSummary={summary}
        />
      </div>

      <Card>
        <CardContent className="pt-4">
          {loading ? <ResultsLoadingSkeleton /> : <ResultsTable results={results} />}
        </CardContent>
      </Card>

      <HumanReviewModal
        result={current} isOpen={reviewOpen}
        onClose={() => setReviewOpen(false)} onSubmit={handleSubmit} onSkip={handleSkip}
        current={reviewIndex + 1} total={reviewable.length}
      />
    </div>
  );
}
