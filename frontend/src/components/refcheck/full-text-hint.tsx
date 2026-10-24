"use client";

import { useState } from "react";
import { ExternalLink, Loader2, RefreshCw } from "lucide-react";
import { APIError, refreshReferenceMetadata } from "@/lib/api";
import { fullTextHint } from "@/lib/full-text";
import type { Reference, RefreshMetadataResponse } from "@/lib/types";

const LINK = "inline-flex items-center gap-0.5 break-all text-blue-700 underline-offset-2 hover:underline dark:text-blue-300";

function DoiLink({ url }: { url: string | null }) {
  if (!url) return null;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className={LINK}>
      DOI <ExternalLink className="h-2.5 w-2.5 shrink-0" />
    </a>
  );
}

/** "Free full text: <link> (licence, version)", or why there is none. */
export function FullTextHint({ reference }: { reference: Reference }) {
  const hint = fullTextHint(reference);
  if (hint.kind === "free") {
    return (
      <p className="text-[11px] leading-snug text-green-800 dark:text-green-300">
        Free full text:{" "}
        <a href={hint.url} target="_blank" rel="noopener noreferrer" className={LINK}>
          {hint.host} <ExternalLink className="h-2.5 w-2.5 shrink-0" />
        </a>
        {hint.pdfUrl && (
          <>
            {" · "}
            <a href={hint.pdfUrl} target="_blank" rel="noopener noreferrer" className={LINK}>
              PDF <ExternalLink className="h-2.5 w-2.5 shrink-0" />
            </a>
          </>
        )}
        {hint.detail && <span className="text-muted-foreground"> ({hint.detail})</span>}
      </p>
    );
  }
  if (hint.kind === "paywalled") {
    return (
      <p className="text-[11px] leading-snug text-amber-800 dark:text-amber-300">
        Paywalled - use institutional access <DoiLink url={hint.doiUrl} />
      </p>
    );
  }
  return (
    <p className="text-[11px] leading-snug text-muted-foreground">
      Free full text not checked yet <DoiLink url={hint.doiUrl} />
    </p>
  );
}

export interface RefreshMetadataCallbacks {
  /** Awaited before the POST (the page snapshots the results to watch a re-verification). */
  onBeforeRefresh?: (refId: number) => Promise<void>;
  /** After a successful refresh; `res.reverification_started` when claims are re-verified. */
  onRefreshed?: (refId: number, res: RefreshMetadataResponse) => void;
}

interface RefreshMetadataButtonProps extends RefreshMetadataCallbacks {
  sessionId: string;
  refId: number;
  /** While this reference is being re-verified (a second run could land last). */
  disabled?: boolean;
}

function refreshNote(res: RefreshMetadataResponse): string {
  const n = res.reverification_started ? res.claims_to_reverify.length : 0;
  if (res.abstract_changed) {
    return n > 0 ? `Abstract updated; ${n} claim${n !== 1 ? "s" : ""} re-verifying` : "Abstract updated";
  }
  return res.changed_fields.length > 0 ? "Free-full-text info updated" : "Nothing new found";
}

/** POST .../refresh-metadata: re-query abstract and open-access copy for one reference. */
export function RefreshMetadataButton(props: RefreshMetadataButtonProps) {
  const { sessionId, refId, onBeforeRefresh, onRefreshed, disabled } = props;
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const refresh = async () => {
    setBusy(true);
    setNote(null);
    try {
      await onBeforeRefresh?.(refId);
      const res = await refreshReferenceMetadata(sessionId, refId);
      setNote(refreshNote(res));
      onRefreshed?.(refId, res);
    } catch (e) {
      setNote(e instanceof APIError && e.status === 404 ? "Reference not found" : "Refresh failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <button
        type="button"
        onClick={refresh}
        disabled={busy || disabled}
        title={disabled ? "Wait until the re-verification finishes" : undefined}
        className="inline-flex items-center gap-1 text-[11px] text-blue-700 hover:underline disabled:opacity-60 dark:text-blue-300"
      >
        {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
        Refresh metadata
      </button>
      {note && <span className="text-[10px] text-muted-foreground" role="status">{note}</span>}
    </span>
  );
}
