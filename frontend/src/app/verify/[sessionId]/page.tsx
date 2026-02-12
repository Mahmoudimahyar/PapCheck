"use client";

import { use } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PipelineTracker } from "@/components/refcheck/pipeline-tracker";
import { BreadcrumbNav } from "@/components/refcheck/breadcrumb-nav";
import { usePipelineSSE } from "@/hooks/use-pipeline-sse";

export default function PipelinePage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);
  const { stages, isComplete, interventionCount, isReconnecting } = usePipelineSSE(sessionId);

  return (
    <div className="space-y-6 max-w-2xl mx-auto">
      <BreadcrumbNav sessionId={sessionId} current="progress" />
      <div>
        <h2 className="text-2xl font-semibold">Verification in Progress</h2>
        <p className="text-sm text-muted-foreground">Session: {sessionId}</p>
      </div>

      {isReconnecting && (
        <Card className="border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950">
          <CardContent className="py-2 flex items-center gap-2">
            <span className="inline-block w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
            <span className="text-sm text-amber-700 dark:text-amber-300">
              Reconnecting to pipeline events...
            </span>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="pt-6">
          <PipelineTracker stages={stages} />
        </CardContent>
      </Card>

      {interventionCount > 0 && (
        <Card className="border-warning">
          <CardContent className="pt-6">
            <p className="text-sm font-medium">
              {interventionCount} item(s) need your attention
            </p>
            <Link href={`/verify/${sessionId}/review`}>
              <Button variant="outline" size="sm" className="mt-2">
                Review matches
              </Button>
            </Link>
          </CardContent>
        </Card>
      )}

      {isComplete && (
        <div className="flex gap-3">
          <Link href={`/verify/${sessionId}/review`}>
            <Button variant="outline">Review References</Button>
          </Link>
          <Link href={`/verify/${sessionId}/results`}>
            <Button variant="outline">Verification Results</Button>
          </Link>
          <Link href={`/verify/${sessionId}/report`}>
            <Button>View Report</Button>
          </Link>
        </div>
      )}
    </div>
  );
}
