"use client";

import { useRef, useState, type ChangeEvent } from "react";
import { APIError, uploadReferencePdf } from "@/lib/api";

export interface UploadMessage {
  text: string;
  tone: "info" | "warn" | "error";
}

export interface ReferenceUploadCallbacks {
  /** Awaited before the upload starts (e.g. to snapshot the current results). */
  onBeforeUpload?: (refId: number) => Promise<void>;
  onPdfUploaded?: (refId: number, claimsToReverify: number[]) => void;
}

/** FastAPI errors arrive as {"detail": "..."}; show the detail, not the JSON. */
function errorText(e: unknown): string {
  if (!(e instanceof APIError)) return "Upload failed. Please try again.";
  try {
    const body: unknown = JSON.parse(e.message);
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
      return `Upload failed: ${body.detail}`;
    }
  } catch { /* plain-text body */ }
  return `Upload failed (HTTP ${e.status}).`;
}

/** One hidden file input shared by every row's Upload / Replace PDF button. */
export function useReferenceUpload(sessionId: string | undefined, callbacks: ReferenceUploadCallbacks) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const targetRef = useRef<number | null>(null);
  const [uploadingRef, setUploadingRef] = useState<number | null>(null);
  const [message, setMessage] = useState<UploadMessage | null>(null);

  const pickFile = (refId: number) => {
    targetRef.current = refId;
    fileInputRef.current?.click();
  };

  const onFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    const refId = targetRef.current;
    e.target.value = "";
    if (!file || refId == null || !sessionId) return;
    setUploadingRef(refId);
    setMessage(null);
    try {
      await callbacks.onBeforeUpload?.(refId);
      const res = await uploadReferencePdf(sessionId, refId, file);
      const ids = res.reverification_started ? res.claims_to_reverify ?? [] : [];
      const count = ids.length === 0
        ? "PDF saved; no claims to re-verify (none left without a manual verdict)."
        : `PDF saved; ${ids.length} claim${ids.length !== 1 ? "s" : ""} will be re-verified.`;
      const mismatch = res.identity_status === "mismatch";
      // The API message names why an identity check failed; keep it when present.
      const text = ids.length > 0 && res.message ? res.message : `${count}${mismatch
        ? " Warning: this PDF does not look like the cited paper (title/author not found)." : ""}`;
      setMessage({ text: `Reference ${refId}: ${text}`, tone: mismatch ? "warn" : "info" });
      callbacks.onPdfUploaded?.(refId, ids);
    } catch (err) {
      setMessage({ text: errorText(err), tone: "error" });
    } finally {
      setUploadingRef(null);
    }
  };

  return { fileInputRef, uploadingRef, message, pickFile, onFileChange };
}
