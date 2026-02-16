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
import {
  CostFromResults,
  ResultsLoadingSkeleton,
  SummaryCard,
} from "@/components/refcheck/results-helpers";
import { BreadcrumbNav } from "@/components/refcheck/breadcrumb-nav";
import { getResults, getReportUrl, overrideVerdict } from "@/lib/api";
import type { ResultsResponse, ResultsSummary, Verdict, VerificationResult } from "@/lib/types";

const EMPTY_SUMMARY: ResultsSummary = {
  total: 0, supported: 0, partially_supported: 0,
  not_supported: 0, contradicted: 0, cannot_verify: 0,
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewIndex, setReviewIndex] = useState(0);

  const fetchResults = useCallback(async () => {
    try {
      setLoading(true); setError(null);
      const filters: { verdict?: string; priority?: string; per_page: number } = { per_page: 200 };
      if (verdictFilter !== "all" && verdictFilter !== "needs_review") filters.verdict = verdictFilter;
      if (priorityFilter !== "all") filters.priority = priorityFilter;
      const data: ResultsResponse = await getResults(sessionId, filters);
      setSummary(data.summary);
      setResults(verdictFilter === "needs_review"
        ? data.results.filter((r) => r.needs_user_review)
        : data.results);
    } catch { setError("Failed to load results."); }
    finally { setLoading(false); }
  }, [sessionId, verdictFilter, priorityFilter]);

  useEffect(() => { fetchResults(); }, [fetchResults]);

  const reviewable = useMemo(() => results.filter((r) => r.needs_user_review && !r.user_override), [results]);
  const needsReviewCount = useMemo(() => results.filter((r) => r.needs_user_review).length, [results]);
  const current = reviewable.length > 0 && reviewIndex < reviewable.length ? reviewable[reviewIndex] : null;

  const handleSubmit = async (verdict: Verdict, reason: string) => {
    if (!current) return;
    try {
      const u = await overrideVerdict(sessionId, current.claim_id, verdict, reason);
      setResults((p) => p.map((r) => r.claim_id === u.claim_id && r.reference_id === u.reference_id ? u : r));
      if (reviewIndex + 1 < reviewable.length) setReviewIndex((i) => i + 1); else setReviewOpen(false);
    } catch { /* user can retry */ }
  };

  const handleSkip = () => {
    if (reviewIndex + 1 < reviewable.length) setReviewIndex((i) => i + 1); else setReviewOpen(false);
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <BreadcrumbNav sessionId={sessionId} current="results" />
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold">Verification Results</h2>
        <div className="flex gap-2">
          <Link href={`/verify/${sessionId}/viewer`}><Button variant="outline" size="sm">Manuscript View</Button></Link>
          <Link href={`/verify/${sessionId}/report`}><Button variant="outline" size="sm">View Report</Button></Link>
          <a href={getReportUrl(sessionId)} download><Button size="sm">Download Report</Button></a>
        </div>
      </div>

      {error && <div className="text-sm text-destructive p-4 border border-destructive/30 rounded">{error}</div>}

      {needsReviewCount > 0 && (
        <Card className="border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950">
          <CardContent className="flex items-center justify-between py-3">
            <div className="flex items-center gap-3">
              <Badge className="bg-amber-500 text-white">{reviewable.length} pending</Badge>
              <span className="text-sm">
                {needsReviewCount} result{needsReviewCount > 1 ? "s" : ""} flagged for human review
              </span>
            </div>
            {reviewable.length > 0 && <Button size="sm" onClick={() => { setReviewIndex(0); setReviewOpen(true); }}>Start Review</Button>}
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-5 gap-3">
        <SummaryCard label="Supported" count={summary.supported} color="text-green-600" bg="bg-green-50" />
        <SummaryCard label="Partial" count={summary.partially_supported} color="text-amber-600" bg="bg-amber-50" />
        <SummaryCard label="Not Supported" count={summary.not_supported} color="text-red-600" bg="bg-red-50" />
        <SummaryCard label="Contradicted" count={summary.contradicted} color="text-red-800" bg="bg-red-100" />
        <SummaryCard label="Can't Verify" count={summary.cannot_verify} color="text-gray-500" bg="bg-gray-50" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="md:col-span-2">
          <CardHeader><h3 className="text-lg font-medium">Verdict Distribution</h3></CardHeader>
          <CardContent><ResultsChart summary={summary} /></CardContent>
        </Card>
        <CostFromResults results={results} />
      </div>

      <ResultsFilterBar
        verdictFilter={verdictFilter} priorityFilter={priorityFilter}
        onVerdictChange={setVerdictFilter} onPriorityChange={setPriorityFilter}
        resultCount={results.length} totalCount={summary.total} loading={loading}
      />

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
