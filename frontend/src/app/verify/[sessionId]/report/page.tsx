"use client";

import { use, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { getReferences, getReportUrl } from "@/lib/api";
import type { Reference } from "@/lib/types";

export default function ReportPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);
  const [references, setReferences] = useState<Reference[]>([]);

  useEffect(() => {
    // Fetch ALL references (not just page 1) so summary is accurate
    async function fetchAll() {
      try {
        const first = await getReferences(sessionId, "all", 1);
        const totalCount = first.total;
        let allRefs = [...first.references];

        // Fetch remaining pages if needed
        const perPage = first.per_page;
        const totalPages = Math.ceil(totalCount / perPage);
        for (let p = 2; p <= totalPages; p++) {
          const page = await getReferences(sessionId, "all", p);
          allRefs = [...allRefs, ...page.references];
        }
        setReferences(allRefs);
      } catch {
        // ignore
      }
    }
    fetchAll();
  }, [sessionId]);

  const total = references.length;
  const found = references.filter((r) => r.source_status === "found").length;
  const notFound = references.filter((r) => r.source_status === "not_found").length;
  const apiError = references.filter((r) => r.source_status === "api_error").length;
  const withPdf = references.filter((r) => r.pdf_path).length;

  return (
    <div className="space-y-6 max-w-2xl mx-auto">
      <h2 className="text-2xl font-semibold">Report</h2>

      <Card>
        <CardHeader>
          <h3 className="text-lg font-medium">Summary</h3>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4">
          <Stat label="Total References" value={total} />
          <Stat label="Found in Databases" value={found} color="text-success" />
          <Stat label="Not Found" value={notFound} color="text-destructive" />
          {apiError > 0 && (
            <Stat label="API Errors" value={apiError} color="text-warning" />
          )}
          <Stat label="PDFs Available" value={withPdf} />
        </CardContent>
      </Card>

      <a href={getReportUrl(sessionId)} download>
        <Button size="lg" className="w-full">
          Download Report (.docx)
        </Button>
      </a>
    </div>
  );
}

function Stat({
  label,
  value,
  color = "text-foreground",
}: {
  label: string;
  value: number;
  color?: string;
}) {
  return (
    <div>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}
