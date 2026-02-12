"use client";

import { use } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ReportPreview } from "@/components/refcheck/report-preview";
import { BreadcrumbNav } from "@/components/refcheck/breadcrumb-nav";

export default function ReportPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <BreadcrumbNav sessionId={sessionId} current="report" />
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold">Report</h2>
        <Link href={`/verify/${sessionId}/results`}>
          <Button variant="outline" size="sm">
            Back to Results
          </Button>
        </Link>
      </div>

      <ReportPreview sessionId={sessionId} />
    </div>
  );
}
