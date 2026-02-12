"use client";

import { use } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PipelineTracker } from "@/components/refcheck/pipeline-tracker";
import { usePipelineSSE } from "@/hooks/use-pipeline-sse";

export default function PipelinePage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);
  const { stages, isComplete, interventionCount } = usePipelineSSE(sessionId);

  return (
    <div className="space-y-6 max-w-2xl mx-auto">
      <div>
        <h2 className="text-2xl font-semibold">Verification in Progress</h2>
        <p className="text-sm text-muted-foreground">Session: {sessionId}</p>
      </div>

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
          <Link href={`/verify/${sessionId}/report`}>
            <Button>View Report</Button>
          </Link>
        </div>
      )}
    </div>
  );
}
