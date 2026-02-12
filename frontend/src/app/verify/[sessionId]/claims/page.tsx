"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { BreadcrumbNav } from "@/components/refcheck/breadcrumb-nav";
import { getClaims, updateClaim, deleteClaim } from "@/lib/api";
import type { Claim } from "@/lib/types";

const TYPE_COLORS: Record<string, string> = {
  factual: "bg-blue-100 text-blue-800",
  methodological: "bg-purple-100 text-purple-800",
  background: "bg-gray-100 text-gray-600",
  attribution: "bg-green-100 text-green-800",
  contrast: "bg-orange-100 text-orange-800",
  interpretive: "bg-teal-100 text-teal-800",
};

const PRIORITY_COLORS: Record<string, string> = {
  high: "bg-red-100 text-red-800 border-red-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-gray-100 text-gray-600 border-gray-200",
};

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

      <div className="flex items-center justify-between">
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
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">#</TableHead>
                  <TableHead>Claim</TableHead>
                  <TableHead className="w-32">Type</TableHead>
                  <TableHead className="w-20">Refs</TableHead>
                  <TableHead className="w-24">Priority</TableHead>
                  <TableHead className="w-16" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {claims.map((claim) => (
                  <TableRow key={claim.id}>
                    <TableCell className="font-mono text-xs">{claim.id}</TableCell>
                    <TableCell>
                      {editingId === claim.id ? (
                        <div className="flex gap-2">
                          <Input
                            value={editText}
                            onChange={(e) => setEditText(e.target.value)}
                            className="text-sm"
                          />
                          <Button size="sm" onClick={() => handleSaveEdit(claim.id)}>
                            Save
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setEditingId(null)}
                          >
                            Cancel
                          </Button>
                        </div>
                      ) : (
                        <p
                          className="text-sm cursor-pointer hover:text-blue-600 transition-colors"
                          onClick={() => {
                            setEditingId(claim.id);
                            setEditText(claim.extracted_claim);
                          }}
                          title="Click to edit"
                        >
                          {claim.extracted_claim}
                        </p>
                      )}
                    </TableCell>
                    <TableCell>
                      <select
                        value={claim.claim_type}
                        onChange={(e) =>
                          handleTypeChange(claim.id, e.target.value)
                        }
                        className="text-xs border rounded px-1 py-0.5 bg-background"
                      >
                        {Object.keys(TYPE_COLORS).map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-0.5">
                        {claim.reference_ids.map((rid) => (
                          <Badge key={rid} variant="outline" className="text-[10px]">
                            {rid}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <select
                        value={claim.priority}
                        onChange={(e) =>
                          handlePriorityChange(claim.id, e.target.value)
                        }
                        className={`text-xs border rounded px-1 py-0.5 ${
                          PRIORITY_COLORS[claim.priority] || ""
                        }`}
                      >
                        <option value="high">high</option>
                        <option value="medium">medium</option>
                        <option value="low">low</option>
                      </select>
                    </TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive hover:text-destructive"
                        onClick={() => handleDelete(claim.id)}
                      >
                        Delete
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ClaimsLoadingSkeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      <div className="h-10 bg-muted rounded w-full" />
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-12 bg-muted/60 rounded w-full" />
      ))}
    </div>
  );
}
