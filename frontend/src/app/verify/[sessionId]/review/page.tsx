"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { GapDashboard } from "@/components/refcheck/gap-dashboard";
import { ReferenceTable } from "@/components/refcheck/reference-table";
import { getReferences } from "@/lib/api";
import type { Reference } from "@/lib/types";

export default function ReviewPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);
  const [references, setReferences] = useState<Reference[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchAll() {
      try {
        const first = await getReferences(sessionId, "all", 1);
        let allRefs = [...first.references];
        const perPage = first.per_page;
        const totalPages = Math.ceil(first.total / perPage);
        for (let p = 2; p <= totalPages; p++) {
          const page = await getReferences(sessionId, "all", p);
          allRefs = [...allRefs, ...page.references];
        }
        setReferences(allRefs);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    fetchAll();
  }, [sessionId]);

  const needsConfirm = references.filter((r) => r.source_status === "pending");
  const unmatched = references.filter((r) => r.source_status === "not_found");

  if (loading) {
    return <p className="text-muted-foreground">Loading references...</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Reference Review</h2>
        <p className="text-sm text-muted-foreground">Session: {sessionId}</p>
      </div>

      <GapDashboard references={references} />

      <Tabs defaultValue="all">
        <TabsList>
          <TabsTrigger value="all">All ({references.length})</TabsTrigger>
          <TabsTrigger value="confirm">
            Needs Confirmation ({needsConfirm.length})
          </TabsTrigger>
          <TabsTrigger value="unmatched">
            Unmatched ({unmatched.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="all">
          <ReferenceTable references={references} />
        </TabsContent>
        <TabsContent value="confirm">
          <ReferenceTable references={needsConfirm} />
        </TabsContent>
        <TabsContent value="unmatched">
          <ReferenceTable references={unmatched} />
        </TabsContent>
      </Tabs>

      <Link href={`/verify/${sessionId}/report`}>
        <Button>Continue to Report</Button>
      </Link>
    </div>
  );
}
