"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ManuscriptViewer } from "@/components/refcheck/manuscript-viewer";
import { EvidencePanel } from "@/components/refcheck/evidence-panel";
import { HighlightLegend } from "@/components/refcheck/highlight-legend";
import { BreadcrumbNav } from "@/components/refcheck/breadcrumb-nav";
import { getManuscript } from "@/lib/api";
import type { ManuscriptResponse } from "@/lib/types";

export default function ViewerPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);
  const [manuscript, setManuscript] = useState<ManuscriptResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedClaimId, setSelectedClaimId] = useState<number | null>(null);
  const [verdictFilter, setVerdictFilter] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getManuscript(sessionId)
      .then(setManuscript)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [sessionId]);

  const allClaimIds = useMemo(() => {
    if (!manuscript) return [];
    return manuscript.paragraphs
      .flatMap((p) => p.claims)
      .sort((a, b) => a.claim_id - b.claim_id)
      .map((c) => c.claim_id);
  }, [manuscript]);

  const handleNavigate = useCallback(
    (direction: "prev" | "next") => {
      if (!selectedClaimId || !allClaimIds.length) return;
      const idx = allClaimIds.indexOf(selectedClaimId);
      if (direction === "prev" && idx > 0) setSelectedClaimId(allClaimIds[idx - 1]);
      if (direction === "next" && idx < allClaimIds.length - 1) setSelectedClaimId(allClaimIds[idx + 1]);
    },
    [selectedClaimId, allClaimIds]
  );

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "ArrowUp" || e.key === "k") handleNavigate("prev");
      if (e.key === "ArrowDown" || e.key === "j") handleNavigate("next");
      if (e.key === "Escape") setSelectedClaimId(null);
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleNavigate]);

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto space-y-4">
        <BreadcrumbNav sessionId={sessionId} current="viewer" />
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-1/3" />
          <div className="h-64 bg-muted rounded" />
        </div>
      </div>
    );
  }

  if (error || !manuscript) {
    return (
      <div className="max-w-7xl mx-auto space-y-4">
        <BreadcrumbNav sessionId={sessionId} current="viewer" />
        <p className="text-red-500">Failed to load manuscript: {error}</p>
        <Link href={`/verify/${sessionId}/results`}>
          <Button variant="outline">Back to Results</Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      <BreadcrumbNav sessionId={sessionId} current="viewer" />
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold">Manuscript Viewer</h2>
        <div className="flex gap-2">
          <Link href={`/verify/${sessionId}/results`}>
            <Button variant="outline" size="sm">Results</Button>
          </Link>
          <Link href={`/verify/${sessionId}/report`}>
            <Button variant="outline" size="sm">Report</Button>
          </Link>
        </div>
      </div>

      <HighlightLegend
        legend={manuscript.legend}
        activeFilter={verdictFilter}
        onFilterClick={setVerdictFilter}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 border rounded-lg overflow-hidden min-h-[600px]">
        <div className="border-r overflow-hidden">
          <ManuscriptViewer
            paragraphs={manuscript.paragraphs}
            selectedClaimId={selectedClaimId}
            verdictFilter={verdictFilter}
            onClaimClick={setSelectedClaimId}
          />
        </div>
        <div className="overflow-hidden">
          <EvidencePanel
            sessionId={sessionId}
            claimId={selectedClaimId}
            onNavigate={handleNavigate}
            onClose={() => setSelectedClaimId(null)}
          />
        </div>
      </div>

      <div className="text-xs text-muted-foreground">
        {manuscript.total_claims} claims · {manuscript.total_paragraphs} paragraphs
        {manuscript.unmapped_claims.length > 0 && (
          <> · {manuscript.unmapped_claims.length} unmapped claims</>
        )}
        {" · Keyboard: ↑↓/jk navigate · Enter select · Esc close"}
      </div>
    </div>
  );
}
