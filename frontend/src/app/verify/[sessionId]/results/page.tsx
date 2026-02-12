"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ResultsChart } from "@/components/refcheck/results-chart";
import { ResultsTable } from "@/components/refcheck/results-table";
import { getResults, getReportUrl } from "@/lib/api";
import type { ResultsResponse, ResultsSummary, VerificationResult } from "@/lib/types";

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

  const fetchResults = useCallback(async () => {
    try {
      setLoading(true);
      const data: ResultsResponse = await getResults(sessionId, {
        verdict: verdictFilter !== "all" ? verdictFilter : undefined,
        priority: priorityFilter !== "all" ? priorityFilter : undefined,
        per_page: 200,
      });
      setSummary(data.summary);
      setResults(data.results);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [sessionId, verdictFilter, priorityFilter]);

  useEffect(() => {
    fetchResults();
  }, [fetchResults]);

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold">Verification Results</h2>
        <div className="flex gap-2">
          <Link href={`/verify/${sessionId}/report`}>
            <Button variant="outline" size="sm">View Report</Button>
          </Link>
          <a href={getReportUrl(sessionId)} download>
            <Button size="sm">Download Report</Button>
          </a>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-5 gap-3">
        <SummaryCard label="Supported" count={summary.supported} color="text-green-600" bg="bg-green-50" />
        <SummaryCard label="Partial" count={summary.partially_supported} color="text-amber-600" bg="bg-amber-50" />
        <SummaryCard label="Not Supported" count={summary.not_supported} color="text-red-600" bg="bg-red-50" />
        <SummaryCard label="Contradicted" count={summary.contradicted} color="text-red-800" bg="bg-red-100" />
        <SummaryCard label="Can't Verify" count={summary.cannot_verify} color="text-gray-500" bg="bg-gray-50" />
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
          <label className="text-xs text-muted-foreground block mb-1">Verdict</label>
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
          </select>
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Priority</label>
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
          {loading ? "Loading..." : `${results.length} of ${summary.total} results`}
        </div>
      </div>

      {/* Results Table */}
      <Card>
        <CardContent className="pt-4">
          <ResultsTable results={results} />
        </CardContent>
      </Card>
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
