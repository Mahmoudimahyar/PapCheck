"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useReverifyWatch } from "@/hooks/use-reverify-watch";
import { getAllReferences, getAllResults } from "@/lib/api";
import type { Reference, RefreshMetadataResponse } from "@/lib/types";

export type RefsByReason = Record<string, Reference[]>;

/**
 * The references behind each cannot-verify reason (loaded the first time `enabled` is true),
 * plus the "Refresh metadata" wiring: a new abstract re-verifies the reference's claims in
 * the background, so the results are snapshotted before the refresh, watched after it, and
 * `onResultsChanged` (the page's results reload) runs once that re-verification settles.
 */
export function useCannotVerifyRefs(
  sessionId: string | undefined,
  enabled: boolean,
  onResultsChanged?: () => void
) {
  const [refsByReason, setRefsByReason] = useState<RefsByReason | null>(null);
  const [failed, setFailed] = useState(false);
  const started = useRef(false); // expanding a second reason must not load again

  const load = useCallback(async () => {
    if (!sessionId) return;
    started.current = true;
    try {
      const [results, references] = await Promise.all([
        getAllResults(sessionId, { verdict: "cannot_verify" }),
        getAllReferences(sessionId),
      ]);
      const byId = new Map(references.map((r) => [r.id, r]));
      const out: RefsByReason = {};
      for (const result of results.results) {
        const ref = byId.get(result.reference_id);
        if (!ref) continue;
        const list = (out[result.cannot_verify_reason || "unknown"] ??= []);
        if (!list.some((r) => r.id === ref.id)) list.push(ref);
      }
      for (const list of Object.values(out)) list.sort((a, b) => a.id - b.id);
      setRefsByReason(out);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [sessionId]);

  useEffect(() => {
    if (enabled && !started.current) load();
  }, [enabled, load]);

  const settled = useCallback(() => {
    void load();
    onResultsChanged?.();
  }, [load, onResultsChanged]);
  // The refresh buttons only render with a session, so "" is never polled.
  const { reverifying, snapshot, watch } = useReverifyWatch(sessionId ?? "", settled);
  const onRefreshed = useCallback((refId: number, res: RefreshMetadataResponse) => {
    void load(); // the abstract / free-full-text hint changed at refresh time
    if (res.reverification_started) void watch(refId, res.claims_to_reverify);
  }, [load, watch]);

  return { refsByReason, failed, reload: load, reverifying, onBeforeRefresh: snapshot, onRefreshed };
}
