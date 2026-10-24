"use client";

import { FileUp, Loader2, Upload } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RefLinks } from "@/components/refcheck/reference-badges";
import {
  FullTextHint,
  RefreshMetadataButton,
  type RefreshMetadataCallbacks,
} from "@/components/refcheck/full-text-hint";
import { ReverifyStatus } from "@/components/refcheck/reverify-status";
import { hasBadPdf, hasUsableFullText } from "@/lib/full-text";
import type { ReverifyState } from "@/hooks/use-reverify-watch";
import type { Reference, ReferenceLinks, SourceIssue } from "@/lib/types";

const BAD_PDF_TITLE =
  "The attached PDF is not the cited article (wrong paper, supplement, scan or metadata page). Replace it with the article itself.";

interface ReferencePdfCellProps extends RefreshMetadataCallbacks {
  reference: Reference;
  issues?: SourceIssue[];
  sessionId?: string;
  links?: ReferenceLinks;
  loadingLinks: boolean;
  uploading: boolean;
  onPickFile: (refId: number) => void;
  reverify?: ReverifyState;
}

function PdfState({ reference: ref }: { reference: Reference }) {
  if (ref.pdf_path) {
    return (
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-xs text-green-700 dark:text-green-400">{ref.pdf_source ?? "available"}</span>
        {ref.identity_status === "mismatch" && (
          <Badge
            variant="outline"
            className="text-[10px] px-1.5 py-0 border-red-300 text-red-600 dark:text-red-400"
            title="The PDF's first pages do not match this reference's title and authors"
          >
            PDF may be wrong paper
          </Badge>
        )}
      </div>
    );
  }
  if (ref.source_status === "found") {
    return (
      <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-amber-300 text-amber-700 dark:text-amber-400">
        Metadata found — PDF needed
      </Badge>
    );
  }
  return <span className="text-xs text-muted-foreground">{ref.journal_url ? "paywalled" : "no PDF"}</span>;
}

/** PDF / links column: state, free-full-text hint, Upload or Replace PDF, re-verify progress. */
export function ReferencePdfCell(props: ReferencePdfCellProps) {
  const { reference: ref, issues, sessionId, links, loadingLinks, uploading, onPickFile, reverify } = props;
  const hasPdf = !!ref.pdf_path;
  const badPdf = hasBadPdf(ref, issues);
  const usable = hasUsableFullText(ref, issues);
  // A second upload (or metadata refresh) while a re-verification runs could let the
  // older run's results land last, so the buttons wait for it.
  const reverifying = reverify?.status === "running";

  return (
    <div className="space-y-1">
      <PdfState reference={ref} />
      {!usable && <FullTextHint reference={ref} />}
      {!usable && links && <RefLinks links={links} />}
      {loadingLinks && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
      {sessionId && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Button
            variant="outline"
            size="sm"
            className={`h-6 text-[10px] px-2 gap-1 ${badPdf
              ? "border-amber-500 bg-amber-50 text-amber-900 hover:bg-amber-100 dark:border-amber-600 dark:bg-amber-950 dark:text-amber-100 dark:hover:bg-amber-900"
              : ""}`}
            title={reverifying ? "Wait until the re-verification finishes"
              : badPdf ? BAD_PDF_TITLE : hasPdf ? "Attach a different PDF for this reference" : undefined}
            onClick={() => onPickFile(ref.id)}
            disabled={uploading || reverifying}
          >
            {uploading ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : hasPdf ? (
              <FileUp className="h-3 w-3" />
            ) : (
              <Upload className="h-3 w-3" />
            )}
            {hasPdf ? "Replace PDF" : "Upload PDF"}
          </Button>
          {!usable && (
            <RefreshMetadataButton
              sessionId={sessionId}
              refId={ref.id}
              onBeforeRefresh={props.onBeforeRefresh}
              onRefreshed={props.onRefreshed}
              disabled={reverifying}
            />
          )}
        </div>
      )}
      {reverify && <ReverifyStatus state={reverify} />}
    </div>
  );
}
