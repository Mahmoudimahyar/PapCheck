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
              <p className="text-sm font-medium">{ref.title || "Untitled"}</p>
              <p className="text-xs text-muted-foreground">
                {ref.authors.slice(0, 2).join(", ")}
                {ref.authors.length > 2 && " et al."}
                {ref.year && ` (${ref.year})`}
              </p>
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
