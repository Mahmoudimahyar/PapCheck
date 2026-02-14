"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ResultsChart } from "@/components/refcheck/results-chart";
import { ResultsTable } from "@/components/refcheck/results-table";
import { HumanReviewModal } from "@/components/refcheck/human-review-modal";
import { BreadcrumbNav } from "@/components/refcheck/breadcrumb-nav";
import { getResults, getReportUrl, overrideVerdict } from "@/lib/api";
import type {
  ResultsResponse,
  ResultsSummary,
  Verdict,
  VerificationResult,
} from "@/lib/types";

const EMPTY_SUMMARY: ResultsSummary = {
  total: 0,
  supported: 0,
  partially_supported: 0,
  not_supported: 0,
  contradicted: 0,
  cannot_verify: 0,
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

  // Review modal state
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewIndex, setReviewIndex] = useState(0);

  const fetchResults = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const filters: {
        verdict?: string;
        priority?: string;
        per_page: number;
      } = { per_page: 200 };

      if (verdictFilter === "needs_review") {
        // Fetch all, then filter client-side for needs_user_review
        filters.per_page = 200;
      } else if (verdictFilter !== "all") {
        filters.verdict = verdictFilter;
      }

      if (priorityFilter !== "all") {
        filters.priority = priorityFilter;
      }

      const data: ResultsResponse = await getResults(sessionId, filters);
      setSummary(data.summary);

      if (verdictFilter === "needs_review") {
        setResults(data.results.filter((r) => r.needs_user_review));
      } else {
        setResults(data.results);
      }
    } catch {
      setError("Failed to load results. Please try refreshing the page.");
    } finally {
      setLoading(false);
    }
  }, [sessionId, verdictFilter, priorityFilter]);

  useEffect(() => {
    fetchResults();
  }, [fetchResults]);

  const reviewableResults = useMemo(
    () => results.filter((r) => r.needs_user_review && !r.user_override),
    [results]
  );

  const needsReviewCount = useMemo(
    () => results.filter((r) => r.needs_user_review).length,
    [results]
  );

  const currentReviewResult =
    reviewableResults.length > 0 && reviewIndex < reviewableResults.length
      ? reviewableResults[reviewIndex]
      : null;

  const handleStartReview = () => {
    setReviewIndex(0);
    setReviewOpen(true);
  };

  const handleReviewSubmit = async (verdict: Verdict, reason: string) => {
    if (!currentReviewResult) return;
    try {
      const updated = await overrideVerdict(
        sessionId,
        currentReviewResult.claim_id,
        verdict,
        reason
      );

      // Update result in local state
      setResults((prev) =>
        prev.map((r) =>
          r.claim_id === updated.claim_id &&
          r.reference_id === updated.reference_id
            ? updated
            : r
        )
      );

      // Advance to next
      if (reviewIndex + 1 < reviewableResults.length) {
        setReviewIndex((i) => i + 1);
      } else {
        setReviewOpen(false);
      }
    } catch {
      // ignore — user can retry
    }
  };

  const handleReviewSkip = () => {
    if (reviewIndex + 1 < reviewableResults.length) {
      setReviewIndex((i) => i + 1);
    } else {
      setReviewOpen(false);
    }
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <BreadcrumbNav sessionId={sessionId} current="results" />
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold">Verification Results</h2>
        <div className="flex gap-2">
          <Link href={`/verify/${sessionId}/viewer`}>
            <Button variant="outline" size="sm">
              Manuscript View
            </Button>
          </Link>
          <Link href={`/verify/${sessionId}/report`}>
            <Button variant="outline" size="sm">
              View Report
            </Button>
          </Link>
          <a href={getReportUrl(sessionId)} download>
            <Button size="sm">Download Report</Button>
          </a>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="text-sm text-destructive p-4 border border-destructive/30 rounded">{error}</div>
      )}

      {/* Needs Review Banner */}
      {needsReviewCount > 0 && (
        <Card className="border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950">
          <CardContent className="flex items-center justify-between py-3">
            <div className="flex items-center gap-3">
              <Badge className="bg-amber-500 text-white">
                {reviewableResults.length} pending
              </Badge>
              <span className="text-sm">
                {needsReviewCount} result
                {needsReviewCount > 1 ? "s" : ""} flagged for human review
                {reviewableResults.length < needsReviewCount && (
                  <span className="text-muted-foreground">
                    {" "}
                    ({needsReviewCount - reviewableResults.length} already
                    overridden)
                  </span>
                )}
              </span>
            </div>
            {reviewableResults.length > 0 && (
              <Button size="sm" onClick={handleStartReview}>
                Start Review
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-5 gap-3">
        <SummaryCard
          label="Supported"
          count={summary.supported}
          color="text-green-600"
          bg="bg-green-50"
        />
        <SummaryCard
          label="Partial"
          count={summary.partially_supported}
          color="text-amber-600"
          bg="bg-amber-50"
        />
        <SummaryCard
          label="Not Supported"
          count={summary.not_supported}
          color="text-red-600"
          bg="bg-red-50"
        />
        <SummaryCard
          label="Contradicted"
          count={summary.contradicted}
          color="text-red-800"
          bg="bg-red-100"
        />
        <SummaryCard
          label="Can't Verify"
          count={summary.cannot_verify}
          color="text-gray-500"
          bg="bg-gray-50"
        />
      </div>

      {/* Chart */}
      <Card>
        <CardHeader>
          <h3 className="text-lg font-medium">Verdict Distribution</h3>
        </CardHeader>
        <CardContent>
          <ResultsChart summary={summary} />
        </CardContent>
      </Card>

      {/* Filter Bar */}
      <div className="flex gap-4 items-center">
        <div>
          <label className="text-xs text-muted-foreground block mb-1">
            Verdict
          </label>
          <select
            value={verdictFilter}
            onChange={(e) => setVerdictFilter(e.target.value)}
            className="border rounded px-2 py-1 text-sm bg-background"
          >
            <option value="all">All</option>
            <option value="supported">Supported</option>
            <option value="partially_supported">Partially Supported</option>
            <option value="not_supported">Not Supported</option>
            <option value="contradicted">Contradicted</option>
            <option value="cannot_verify">Cannot Verify</option>
            <option value="needs_review">Needs Review</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">
            Priority
          </label>
          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
            className="border rounded px-2 py-1 text-sm bg-background"
          >
            <option value="all">All</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
        <div className="ml-auto text-sm text-muted-foreground">
          {loading
            ? "Loading..."
            : `${results.length} of ${summary.total} results`}
        </div>
      </div>

      {/* Results Table */}
      <Card>
        <CardContent className="pt-4">
          {loading ? (
            <ResultsLoadingSkeleton />
          ) : (
            <ResultsTable results={results} />
          )}
        </CardContent>
      </Card>

      {/* Human Review Modal */}
      <HumanReviewModal
        result={currentReviewResult}
        isOpen={reviewOpen}
        onClose={() => setReviewOpen(false)}
        onSubmit={handleReviewSubmit}
        onSkip={handleReviewSkip}
        current={reviewIndex + 1}
        total={reviewableResults.length}
      />
    </div>
  );
}

function ResultsLoadingSkeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      <div className="h-10 bg-muted rounded w-full" />
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="h-12 bg-muted/60 rounded w-full" />
      ))}
    </div>
  );
}

function SummaryCard({
  label,
  count,
  color,
  bg,
}: {
  label: string;
  count: number;
  color: string;
  bg: string;
}) {
  return (
    <Card className={bg}>
      <CardContent className="pt-4 text-center">
        <p className={`text-3xl font-bold ${color}`}>{count}</p>
        <p className="text-xs text-muted-foreground mt-1">{label}</p>
      </CardContent>
    </Card>
  );
}
