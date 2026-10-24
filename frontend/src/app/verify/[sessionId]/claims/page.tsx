"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { BreadcrumbNav } from "@/components/refcheck/breadcrumb-nav";
import { ClaimsLoadingSkeleton, ClaimsTable } from "@/components/refcheck/claims-table";
import { getClaims, updateClaim, deleteClaim } from "@/lib/api";
import type { Claim } from "@/lib/types";

export default function ClaimsPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");

  const fetchClaims = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getClaims(sessionId);
      setClaims(data);
    } catch {
      setError("Failed to load claims.");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    fetchClaims();
  }, [fetchClaims]);

  const handleDelete = async (claimId: number) => {
    try {
      await deleteClaim(sessionId, claimId);
      setClaims((prev) => prev.filter((c) => c.id !== claimId));
    } catch {
      /* ignore */
    }
  };

  const handleSaveEdit = async (claimId: number) => {
    try {
      const updated = await updateClaim(sessionId, claimId, {
        extracted_claim: editText,
      });
      setClaims((prev) => prev.map((c) => (c.id === claimId ? updated : c)));
      setEditingId(null);
    } catch {
      /* ignore */
    }
  };

  const handleTypeChange = async (claimId: number, newType: string) => {
    try {
      const updated = await updateClaim(sessionId, claimId, {
        claim_type: newType as Claim["claim_type"],
      });
      setClaims((prev) => prev.map((c) => (c.id === claimId ? updated : c)));
    } catch {
      /* ignore */
    }
  };

  const handlePriorityChange = async (claimId: number, newPriority: string) => {
    try {
      const updated = await updateClaim(sessionId, claimId, {
        priority: newPriority as Claim["priority"],
      });
      setClaims((prev) => prev.map((c) => (c.id === claimId ? updated : c)));
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <BreadcrumbNav sessionId={sessionId} current="claims" />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-semibold">Claims Review</h2>
          <p className="text-sm text-muted-foreground">
            {claims.length} claims extracted — edit or remove before verification
          </p>
        </div>
        <Link href={`/verify/${sessionId}/results`}>
          <Button>Confirm and Start Verification</Button>
        </Link>
      </div>

      {error && (
        <div className="text-sm text-destructive p-4 border border-destructive/30 rounded">
          {error}
        </div>
      )}

      <Card>
        <CardContent className="pt-4">
          {loading ? (
            <ClaimsLoadingSkeleton />
          ) : (
            <ClaimsTable
              claims={claims}
              editingId={editingId}
              editText={editText}
              onEditTextChange={setEditText}
              onStartEdit={(claim) => {
                setEditingId(claim.id);
                setEditText(claim.extracted_claim);
              }}
              onCancelEdit={() => setEditingId(null)}
              onSaveEdit={handleSaveEdit}
              onTypeChange={handleTypeChange}
              onPriorityChange={handlePriorityChange}
              onDelete={handleDelete}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
