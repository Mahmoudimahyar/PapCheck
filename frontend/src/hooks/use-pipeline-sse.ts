"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getEventsUrl } from "@/lib/api";
import { connectSSE } from "@/lib/sse";
import type { PipelineEvent, StageStatus } from "@/lib/types";

const INITIAL_STAGES: StageStatus[] = [
  { stage: 1, name: "Parse Manuscript", status: "pending", elapsed_seconds: 0, progress_current: 0, progress_total: 0, message: "" },
  { stage: 2, name: "Detect Citations", status: "pending", elapsed_seconds: 0, progress_current: 0, progress_total: 0, message: "" },
  { stage: 3, name: "Match PDFs", status: "pending", elapsed_seconds: 0, progress_current: 0, progress_total: 0, message: "" },
  { stage: 4, name: "Resolve Gaps", status: "pending", elapsed_seconds: 0, progress_current: 0, progress_total: 0, message: "" },
  { stage: 5, name: "Verify Claims", status: "pending", elapsed_seconds: 0, progress_current: 0, progress_total: 0, message: "" },
  { stage: 6, name: "Missing Citations", status: "pending", elapsed_seconds: 0, progress_current: 0, progress_total: 0, message: "" },
  { stage: 7, name: "Generate Report", status: "pending", elapsed_seconds: 0, progress_current: 0, progress_total: 0, message: "" },
];

export function usePipelineSSE(sessionId: string) {
  const [stages, setStages] = useState<StageStatus[]>(INITIAL_STAGES);
  const [isComplete, setIsComplete] = useState(false);
  const [interventionCount, setInterventionCount] = useState(0);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const closeRef = useRef<(() => void) | null>(null);

  const handleEvent = useCallback((event: PipelineEvent) => {
    setIsReconnecting(false);

    if (event.status === "pipeline_complete") {
      setIsComplete(true);
      return;
    }

    if (event.status === "error" && (!event.stage || event.stage === 0)) {
      setStages((prev) =>
        prev.map((s) =>
          s.status === "pending" || s.status === "running"
            ? { ...s, status: "error", message: event.message ?? "Pipeline error" }
            : s
        )
      );
      return;
    }

    if (event.status === "needs_input" && event.intervention) {
      setInterventionCount((prev) => prev + 1);
    }

    if (event.stage && event.stage > 0) {
      setStages((prev) =>
        prev.map((s) => {
          if (s.stage !== event.stage) return s;
          return {
            ...s,
            status: event.status === "pipeline_complete" ? "complete" : event.status,
            elapsed_seconds: event.elapsed_seconds ?? s.elapsed_seconds,
            progress_current: event.progress?.current ?? s.progress_current,
            progress_total: event.progress?.total ?? s.progress_total,
            message: event.message ?? s.message,
          };
        })
      );
    }
  }, []);

  const handleError = useCallback(() => {
    setIsReconnecting(true);
  }, []);

  useEffect(() => {
    const url = getEventsUrl(sessionId);
    closeRef.current = connectSSE(url, handleEvent, handleError);
    return () => closeRef.current?.();
  }, [sessionId, handleEvent, handleError]);

  return { stages, isComplete, interventionCount, isReconnecting };
}
