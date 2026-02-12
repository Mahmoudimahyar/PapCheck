"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  getReportPreview,
  regenerateReport,
  getReportUrl,
} from "@/lib/api";
import type { ReportPreview as ReportPreviewType } from "@/lib/types";

interface ReportPreviewProps {
  sessionId: string;
}

const VERDICT_COLORS: Record<string, string> = {
  supported:
    "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  partially_supported:
    "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  not_supported:
    "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  contradicted:
    "bg-red-200 text-red-900 dark:bg-red-800 dark:text-red-100",
  cannot_verify:
    "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200",
};

export function ReportPreview({ sessionId }: ReportPreviewProps) {
  const [preview, setPreview] = useState<ReportPreviewType | null>(null);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPreview = useCallback(async () => {
    try {
      setLoading(true);
      const data = await getReportPreview(sessionId);
      setPreview(data);
      setError(null);
    } catch {
      setError("Failed to load report preview");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    fetchPreview();
  }, [fetchPreview]);

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      await regenerateReport(sessionId);
      await fetchPreview();
    } catch {
      setError("Failed to regenerate report");
    } finally {
      setRegenerating(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-16 bg-muted rounded" />
          ))}
        </div>
        <div className="h-24 bg-muted rounded" />
        <div className="h-32 bg-muted rounded" />
      </div>
    );
  }

  if (error || !preview) {
    return (
      <div className="text-sm text-destructive">
        {error || "No preview available"}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {Object.entries(preview.summary)
          .filter(([k]) => k !== "total")
          .map(([key, count]) => (
            <Card key={key} className="text-center">
              <CardContent className="pt-4 pb-3">
                <div className="text-2xl font-bold">{count}</div>
                <div className="text-xs text-muted-foreground capitalize">
                  {key.replace("_", " ")}
                </div>
              </CardContent>
            </Card>
          ))}
      </div>

      {/* Retracted References Warning */}
      {preview.retracted.length > 0 && (
        <Card className="border-red-300 dark:border-red-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-red-600 text-base">
              Retracted or Corrected References
            </CardTitle>
          </CardHeader>
          <CardContent>
            {preview.retracted.map((r, i) => (
              <div key={i} className="flex items-center gap-2 py-1">
                <Badge variant="destructive" className="text-xs">
                  {r.status?.toUpperCase()}
                </Badge>
                <span className="text-sm">
                  [{r.ref_id}] {r.title}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Critical Findings */}
      {preview.critical_findings.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Critical Findings</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {preview.critical_findings.map((f, i) => (
              <div key={i} className="p-2 border rounded text-sm">
                <div className="flex items-center gap-2">
                  <Badge className={VERDICT_COLORS[f.verdict] || ""}>
                    {f.verdict?.replace("_", " ")}
                  </Badge>
                  <span className="font-medium">Claim {f.claim_id}</span>
                </div>
                <p className="mt-1 text-muted-foreground">{f.claim}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Minor Issues */}
      {preview.minor_issues.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Minor Issues</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {preview.minor_issues.map((f, i) => (
              <div key={i} className="p-2 border rounded text-sm">
                <Badge className={VERDICT_COLORS.partially_supported}>
                  Partially Supported
                </Badge>
                <span className="ml-2">
                  Claim {f.claim_id}: {f.claim}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Actions */}
      <div className="flex gap-3 items-center">
        <Button asChild>
          <a href={getReportUrl(sessionId)} download>
            Download Report (DOCX)
          </a>
        </Button>
        {preview.overrides_count > 0 && (
          <Button
            variant="outline"
            onClick={handleRegenerate}
            disabled={regenerating}
          >
            {regenerating ? "Regenerating..." : "Regenerate Report"}
          </Button>
        )}
        <span className="text-xs text-muted-foreground">
          Generated:{" "}
          {preview.generated_at
            ? new Date(preview.generated_at).toLocaleString()
            : "N/A"}
        </span>
      </div>
    </div>
  );
}
