"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
  high: "bg-red-100 text-red-800 border-red-200 dark:bg-red-900 dark:text-red-200 dark:border-red-800",
  medium: "bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-900 dark:text-amber-200 dark:border-amber-800",
  low: "bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700",
};

export interface ClaimsTableProps {
  claims: Claim[];
  editingId: number | null;
  editText: string;
  onEditTextChange: (text: string) => void;
  onStartEdit: (claim: Claim) => void;
  onCancelEdit: () => void;
  onSaveEdit: (claimId: number) => void;
  onTypeChange: (claimId: number, newType: string) => void;
  onPriorityChange: (claimId: number, newPriority: string) => void;
  onDelete: (claimId: number) => void;
}

/** The editable claims list of the Claims Review page (claims/page.tsx holds the state). */
export function ClaimsTable(props: ClaimsTableProps) {
  return (
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
        {props.claims.map((claim) => (
          <ClaimRow key={claim.id} claim={claim} {...props} />
        ))}
      </TableBody>
    </Table>
  );
}

function ClaimRow({
  claim,
  editingId,
  editText,
  onEditTextChange,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onTypeChange,
  onPriorityChange,
  onDelete,
}: ClaimsTableProps & { claim: Claim }) {
  return (
    <TableRow>
      <TableCell className="font-mono text-xs">{claim.id}</TableCell>
      <TableCell className="min-w-64 whitespace-normal">
        {editingId === claim.id ? (
          <div className="flex gap-2">
            <Input
              value={editText}
              onChange={(e) => onEditTextChange(e.target.value)}
              className="text-sm"
            />
            <Button size="sm" onClick={() => onSaveEdit(claim.id)}>
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={onCancelEdit}>
              Cancel
            </Button>
          </div>
        ) : (
          <p
            className="text-sm cursor-pointer hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
            onClick={() => onStartEdit(claim)}
            title="Click to edit"
          >
            {claim.extracted_claim}
          </p>
        )}
      </TableCell>
      <TableCell>
        <select
          value={claim.claim_type}
          onChange={(e) => onTypeChange(claim.id, e.target.value)}
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
          onChange={(e) => onPriorityChange(claim.id, e.target.value)}
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
          onClick={() => onDelete(claim.id)}
        >
          Delete
        </Button>
      </TableCell>
    </TableRow>
  );
}

export function ClaimsLoadingSkeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      <div className="h-10 bg-muted rounded w-full" />
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-12 bg-muted/60 rounded w-full" />
      ))}
    </div>
  );
}
