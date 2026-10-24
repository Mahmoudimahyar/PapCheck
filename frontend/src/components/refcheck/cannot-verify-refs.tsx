"use client";

import {
  FullTextHint,
  RefreshMetadataButton,
  type RefreshMetadataCallbacks,
} from "@/components/refcheck/full-text-hint";
import { referenceYear } from "@/components/refcheck/reference-badges";
import { ReverifyStatus } from "@/components/refcheck/reverify-status";
import type { ReverifyState } from "@/hooks/use-reverify-watch";
import { FULL_TEXT_REASONS } from "@/lib/full-text";
import type { Reference } from "@/lib/types";

interface CannotVerifyRefListProps extends RefreshMetadataCallbacks {
  reason: string;
  /** undefined while loading; [] when no reference could be matched. */
  references: Reference[] | undefined;
  failed: boolean;
  sessionId?: string;
  /** Re-verification progress per reference id after a metadata refresh. */
  reverifying?: Record<number, ReverifyState>;
}

/** References behind one cannot-verify reason, with the free-full-text hint where it helps. */
export function CannotVerifyRefList(props: CannotVerifyRefListProps) {
  const { reason, references, failed, sessionId, reverifying } = props;
  if (failed) return <p className="text-muted-foreground">Could not load the references for this reason.</p>;
  if (!references) return <p className="text-muted-foreground">Loading references...</p>;
  if (references.length === 0) return null;
  return (
    <ul className="mt-1 space-y-1.5">
      {references.map((ref) => {
        // A better copy only helps when the full text was missing or unusable.
        const showHint = FULL_TEXT_REASONS.has(reason) || !ref.pdf_path;
        const reverify = reverifying?.[ref.id];
        return (
          <li key={ref.id} className="min-w-0">
            <p className="break-words text-gray-700 dark:text-gray-300">
              <span className="font-mono">[{ref.id}]</span> {ref.title || "Untitled"}
              {ref.year ? ` (${referenceYear(ref)})` : ""}
            </p>
            {showHint && (
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <FullTextHint reference={ref} />
                {sessionId && (
                  <RefreshMetadataButton
                    sessionId={sessionId}
                    refId={ref.id}
                    onBeforeRefresh={props.onBeforeRefresh}
                    onRefreshed={props.onRefreshed}
                    disabled={reverify?.status === "running"}
                  />
                )}
              </div>
            )}
            {reverify && <ReverifyStatus state={reverify} />}
          </li>
        );
      })}
    </ul>
  );
}
