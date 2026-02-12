"use client";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Reference } from "@/lib/types";

interface ReferenceTableProps {
  references: Reference[];
}

const STATUS_COLORS: Record<string, string> = {
  found: "bg-success/10 text-success",
  not_found: "bg-destructive/10 text-destructive",
  api_error: "bg-warning/10 text-warning",
  pending: "bg-muted text-muted-foreground",
};

const RETRACTION_BADGE: Record<string, { label: string; className: string }> = {
  retracted: { label: "RETRACTED", className: "bg-red-700 text-white" },
  corrected: { label: "CORRECTED", className: "bg-amber-600 text-white" },
  expression_of_concern: { label: "CONCERN", className: "bg-orange-500 text-white" },
};

export function ReferenceTable({ references }: ReferenceTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-12">#</TableHead>
          <TableHead>Reference</TableHead>
          <TableHead className="w-28">Status</TableHead>
          <TableHead className="w-28">PDF</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {references.map((ref) => (
          <TableRow key={ref.id}>
            <TableCell className="font-mono text-xs">{ref.id}</TableCell>
            <TableCell>
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium">{ref.title || "Untitled"}</p>
                {ref.retraction_status && RETRACTION_BADGE[ref.retraction_status] && (
                  <Badge className={RETRACTION_BADGE[ref.retraction_status].className + " text-[10px] px-1.5 py-0"}>
                    {RETRACTION_BADGE[ref.retraction_status].label}
                  </Badge>
                )}
                {ref.duplicate_of != null && (
                  <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-muted-foreground">
                    Dup of [{ref.duplicate_of}]
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                {ref.authors.slice(0, 2).join(", ")}
                {ref.authors.length > 2 && " et al."}
                {ref.year && ` (${ref.year})`}
              </p>
              {ref.retraction_detail && (
                <p className="text-xs text-red-600 dark:text-red-400 mt-0.5">
                  {ref.retraction_detail}
                </p>
              )}
            </TableCell>
            <TableCell>
              <Badge variant="outline" className={STATUS_COLORS[ref.source_status]}>
                {ref.source_status}
              </Badge>
            </TableCell>
            <TableCell className="text-xs text-muted-foreground">
              {ref.pdf_source || (ref.journal_url ? "paywalled" : "—")}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
