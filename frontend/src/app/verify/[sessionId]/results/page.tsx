"use client";

import { use } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export default function ResultsPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);

  return (
    <div className="space-y-6 max-w-2xl mx-auto">
      <h2 className="text-2xl font-semibold">Verification Results</h2>
      <Card>
        <CardContent className="pt-6">
          <p className="text-muted-foreground">
            Claim verification is a V1 feature. In the MVP, the report shows
            reference existence status only.
          </p>
        </CardContent>
      </Card>
      <Link href={`/verify/${sessionId}/report`}>
        <Button>View Report</Button>
      </Link>
    </div>
  );
}
