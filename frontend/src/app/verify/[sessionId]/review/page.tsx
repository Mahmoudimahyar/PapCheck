"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { GapDashboard } from "@/components/refcheck/gap-dashboard";
import { ReferenceTable } from "@/components/refcheck/reference-table";
import { BreadcrumbNav } from "@/components/refcheck/breadcrumb-nav";
import { ReverifyBanner } from "@/components/refcheck/reverify-status";
import { SourceIssuesCard, issuesByReference } from "@/components/refcheck/source-issues-card";
import { useReverifyWatch } from "@/hooks/use-reverify-watch";
import { getAllReferences, getSourceIssues } from "@/lib/api";
import type { Reference, RefreshMetadataResponse, SourceIssue } from "@/lib/types";

export default function ReviewPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);
  const [references, setReferences] = useState<Reference[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [issues, setIssues] = useState<SourceIssue[]>([]);
  const issuesByRef = useMemo(() => issuesByReference(issues), [issues]);

  // First load shows the skeleton / error; later reloads (after an upload, a metadata
  // refresh or a finished re-verification) keep the current table on failure.
  const reload = useCallback(async (initial = false) => {
    // Optional: older backends have no /source-issues endpoint
    getSourceIssues(sessionId).then((r) => setIssues(r.issues)).catch(() => { if (initial) setIssues([]); });
    try {
      setReferences(await getAllReferences(sessionId));
    } catch {
      if (initial) setError("Failed to load references. Please try refreshing the page.");
    } finally {
      if (initial) setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => { reload(true); }, [reload]);

  const reloadQuietly = useCallback(() => { void reload(); }, [reload]);
  const { reverifying, snapshot, watch } = useReverifyWatch(sessionId, reloadQuietly);
  const handlePdfUploaded = useCallback((refId: number, claimIds: number[]) => {
    void reload(); // pdf_path / identity_status changed at upload time
    void watch(refId, claimIds);
  }, [reload, watch]);
  // A new abstract re-verifies the reference's claims in the background, like an upload;
  // watching also locks Replace PDF so an older run cannot land last.
  const handleRefreshed = useCallback((refId: number, res: RefreshMetadataResponse) => {
    void reload(); // abstract / free-full-text hint changed at refresh time
    if (res.reverification_started) void watch(refId, res.claims_to_reverify);
  }, [reload, watch]);

  const tableProps = {
    sessionId,
    issuesByRef,
    reverifying,
    onBeforeUpload: snapshot,
    onPdfUploaded: handlePdfUploaded,
    onBeforeRefresh: snapshot,
    onReferenceRefreshed: handleRefreshed,
  };
  const needsConfirm = references.filter((r) => r.source_status === "pending");
  const unmatched = references.filter((r) => r.source_status === "not_found");

  return (
    <div className="space-y-6">
      <BreadcrumbNav sessionId={sessionId} current="review" />
      {loading ? (
        <LoadingSkeleton />
      ) : error ? (
        <div className="text-sm text-destructive p-4 border border-destructive/30 rounded">{error}</div>
      ) : (
        <>
          <div>
            <h2 className="text-2xl font-semibold">Reference Review</h2>
            <p className="text-sm text-muted-foreground break-all">Session: {sessionId}</p>
          </div>

          <ReverifyBanner states={reverifying} />
          <GapDashboard references={references} />
          <SourceIssuesCard issues={issues} />

          <Tabs defaultValue="all">
            <TabsList className="max-w-full overflow-x-auto justify-start">
              <TabsTrigger value="all">All ({references.length})</TabsTrigger>
              <TabsTrigger value="confirm">
                Needs Confirmation ({needsConfirm.length})
              </TabsTrigger>
              <TabsTrigger value="unmatched">
                Unmatched ({unmatched.length})
              </TabsTrigger>
            </TabsList>

            <TabsContent value="all">
              <ReferenceTable references={references} {...tableProps} />
            </TabsContent>
            <TabsContent value="confirm">
              <ReferenceTable references={needsConfirm} {...tableProps} />
            </TabsContent>
            <TabsContent value="unmatched">
              <ReferenceTable references={unmatched} {...tableProps} />
            </TabsContent>
          </Tabs>

          <Link href={`/verify/${sessionId}/report`}>
            <Button>Continue to Report</Button>
          </Link>
        </>
      )}
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-8 w-48 bg-muted rounded" />
      <div className="h-4 w-32 bg-muted rounded" />
      <div className="flex gap-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-8 w-24 bg-muted rounded" />
        ))}
      </div>
      <div className="space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-12 bg-muted rounded" />
        ))}
      </div>
    </div>
  );
}
