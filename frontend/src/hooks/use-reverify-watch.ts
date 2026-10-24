"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getAllResults } from "@/lib/api";
import type { VerificationResult } from "@/lib/types";

// The backend re-verifies in a background task and emits no event when it ends,
// so the page polls the stored results until every re-verified pair has changed.
const POLL_MS = 5000;
const MAX_POLLS = 36; // 3 minutes; a few pairs usually take well under one

export interface ReverifyState {
  claimIds: number[];
  /** Pairs whose stored result changed since the upload / refresh. */
  done: number;
  status: "running" | "done" | "timeout";
  /** Verdict counts of the changed pairs. */
  verdicts: Record<string, number>;
}

/** claim_id -> result fingerprint, for one reference's pairs. */
type Fingerprints = Map<number, string>;

function fingerprints(results: VerificationResult[], refId: number): Fingerprints {
  const out: Fingerprints = new Map();
  for (const r of results) {
    if (r.reference_id !== refId) continue;
    out.set(r.claim_id, JSON.stringify([
      r.verdict, r.confidence, r.reasoning, r.source_coverage, r.cannot_verify_reason ?? null,
      r.decided_by ?? null, r.layer_path ?? null, r.cost_usd ?? null, r.latency_ms ?? null,
    ]));
  }
  return out;
}

function countVerdicts(results: VerificationResult[], refId: number, claimIds: number[]): Record<string, number> {
  const wanted = new Set(claimIds);
  const out: Record<string, number> = {};
  for (const r of results) {
    if (r.reference_id === refId && wanted.has(r.claim_id)) out[r.verdict] = (out[r.verdict] ?? 0) + 1;
  }
  return out;
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * `snapshot(refId)` before an upload or metadata refresh, `watch(refId, claimIds)` after it.
 * `onSettled` runs once the pairs are re-verified (or polling gives up) so the page reloads.
 */
export function useReverifyWatch(sessionId: string, onSettled: () => void) {
  const [states, setStates] = useState<Record<number, ReverifyState>>({});
  const baselines = useRef(new Map<number, Fingerprints>());
  const generation = useRef(new Map<number, number>());
  const alive = useRef(true);
  const settled = useRef(onSettled);

  useEffect(() => { settled.current = onSettled; }, [onSettled]);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const snapshot = useCallback(async (refId: number) => {
    try {
      baselines.current.set(refId, fingerprints((await getAllResults(sessionId)).results, refId));
    } catch {
      baselines.current.set(refId, new Map()); // unknown baseline: only new pairs count as done
    }
  }, [sessionId]);

  const watch = useCallback(async (refId: number, claimIds: number[]) => {
    if (claimIds.length === 0) return;
    const gen = (generation.current.get(refId) ?? 0) + 1;
    generation.current.set(refId, gen); // a newer upload of the same reference takes over
    const baseline = baselines.current.get(refId) ?? new Map<number, string>();
    const current = () => alive.current && generation.current.get(refId) === gen;
    const update = (s: ReverifyState) => setStates((prev) => ({ ...prev, [refId]: s }));
    update({ claimIds, done: 0, status: "running", verdicts: {} });

    for (let i = 0; i < MAX_POLLS; i++) {
      await sleep(POLL_MS);
      if (!current()) return;
      let results: VerificationResult[];
      try {
        results = (await getAllResults(sessionId)).results;
      } catch {
        continue; // transient API problem: try again next tick
      }
      if (!current()) return;
      const now = fingerprints(results, refId);
      const changed = claimIds.filter((id) => now.has(id) && now.get(id) !== baseline.get(id));
      const verdicts = countVerdicts(results, refId, changed);
      const finished = changed.length === claimIds.length;
      update({ claimIds, done: changed.length, status: finished ? "done" : "running", verdicts });
      if (finished) {
        settled.current();
        return;
      }
    }
    if (!current()) return;
    setStates((prev) => ({ ...prev, [refId]: { ...prev[refId], status: "timeout" } }));
    settled.current();
  }, [sessionId]);

  return { reverifying: states, snapshot, watch };
}
