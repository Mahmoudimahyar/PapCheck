"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ReferenceBadges, referenceYear } from "@/components/refcheck/reference-badges";
import { ReferencePdfCell } from "@/components/refcheck/reference-pdf-cell";
import { useReferenceUpload, type UploadMessage } from "@/hooks/use-reference-upload";
import type { ReverifyState } from "@/hooks/use-reverify-watch";
import { getReferenceLinks } from "@/lib/api";
import { hasUsableFullText } from "@/lib/full-text";
import type { Reference, ReferenceLinks, RefreshMetadataResponse, SourceIssue } from "@/lib/types";

interface ReferenceTableProps {
  references: Reference[];
  sessionId?: string;
  /** Awaited before an upload starts (the review page snapshots results here). */
  onBeforeUpload?: (refId: number) => Promise<void>;
  onPdfUploaded?: (refId: number, claimsToReverify: number[]) => void;
  /** V5.2: bibliography / source issues per reference id (badges on the row). */
  issuesByRef?: Record<number, SourceIssue[]>;
  /** Re-verification progress per reference id after an upload or a new abstract. */
  reverifying?: Record<number, ReverifyState>;
  /** Awaited before "Refresh metadata" posts (the review page snapshots results here). */
  onBeforeRefresh?: (refId: number) => Promise<void>;
  /** After "Refresh metadata" succeeded for a reference. */
  onReferenceRefreshed?: (refId: number, res: RefreshMetadataResponse) => void;
}

const STATUS_COLORS: Record<string, string> = {
  found: "bg-success/10 text-green-800 dark:text-success",
  not_found: "bg-destructive/10 text-red-700 dark:text-destructive",
  api_error: "bg-warning/10 text-amber-800 dark:text-warning",
  pending: "bg-muted text-stone-600 dark:text-muted-foreground",
};

const MESSAGE_TONES: Record<UploadMessage["tone"], string> = {
  info: "bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300",
  warn: "bg-amber-50 dark:bg-amber-950 border-amber-300 dark:border-amber-700 text-amber-900 dark:text-amber-100",
  error: "bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800 text-red-700 dark:text-red-300",
};

export function ReferenceTable(props: ReferenceTableProps) {
  const { references, sessionId, onBeforeUpload, onPdfUploaded, issuesByRef, reverifying } = props;
  const [linksCache, setLinksCache] = useState<Record<number, ReferenceLinks>>({});
  const [loadingLinks, setLoadingLinks] = useState<Set<number>>(new Set());
  const requested = useRef(new Set<number>());
  const upload = useReferenceUpload(sessionId, { onBeforeUpload, onPdfUploaded });

  const fetchLinks = useCallback(async (refId: number) => {
    if (!sessionId || requested.current.has(refId)) return;
    requested.current.add(refId);
    setLoadingLinks((prev) => new Set(prev).add(refId));
    try {
      const links = await getReferenceLinks(sessionId, refId);
      setLinksCache((prev) => ({ ...prev, [refId]: links }));
    } catch { /* links are a convenience; the row still works without them */ }
    finally { setLoadingLinks((prev) => { const s = new Set(prev); s.delete(refId); return s; }); }
  }, [sessionId]);

  // Links for every reference without usable full text (no PDF, or a wrong / unusable one).
  useEffect(() => {
    for (const ref of references) {
      if (!hasUsableFullText(ref, issuesByRef?.[ref.id])) fetchLinks(ref.id);
    }
  }, [references, issuesByRef, fetchLinks]);

  return (
    <>
      <input
        ref={upload.fileInputRef}
        type="file"
        accept=".pdf,application/pdf"
        className="hidden"
        onChange={upload.onFileChange}
      />
      {upload.message && (
        <div className={`text-sm p-3 mb-3 rounded border ${MESSAGE_TONES[upload.message.tone]}`} role="status">
          {upload.message.text}
        </div>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-12">#</TableHead>
            <TableHead>Reference</TableHead>
            <TableHead className="w-28">Status</TableHead>
            <TableHead className="w-56">PDF / Links</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {references.map((ref) => (
            <TableRow key={ref.id}>
              <TableCell className="font-mono text-xs align-top">{ref.id}</TableCell>
              <TableCell className="min-w-64 whitespace-normal align-top">
                <div className="flex items-center gap-2 flex-wrap">
                  <p className="text-sm font-medium">{ref.title || "Untitled"}</p>
                  <ReferenceBadges reference={ref} issues={issuesByRef?.[ref.id]} />
                </div>
                <p className="text-xs text-muted-foreground">
                  {ref.authors.slice(0, 2).join(", ")}
                  {ref.authors.length > 2 && " et al."}
                  {ref.year && ` (${referenceYear(ref)})`}
                </p>
                {ref.retraction_detail && (
                  <p className="text-xs text-red-600 dark:text-red-400 mt-0.5">
                    {ref.retraction_detail}
                  </p>
                )}
              </TableCell>
              <TableCell className="align-top">
                <Badge variant="outline" className={STATUS_COLORS[ref.source_status]}>
                  {ref.source_status}
                </Badge>
              </TableCell>
              <TableCell className="min-w-48 max-w-72 whitespace-normal align-top">
                <ReferencePdfCell
                  reference={ref}
                  issues={issuesByRef?.[ref.id]}
                  sessionId={sessionId}
                  links={linksCache[ref.id]}
                  loadingLinks={loadingLinks.has(ref.id)}
                  uploading={upload.uploadingRef === ref.id}
                  onPickFile={upload.pickFile}
                  reverify={reverifying?.[ref.id]}
                  onBeforeRefresh={props.onBeforeRefresh}
                  onRefreshed={props.onReferenceRefreshed}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
}
