"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { UploadZone } from "@/components/refcheck/upload-zone";
import { createSession, startPipeline } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  const [manuscript, setManuscript] = useState<File | null>(null);
  const [pdfs, setPdfs] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleStart = async () => {
    if (!manuscript) return;
    setLoading(true);
    setError(null);
    try {
      const session = await createSession(manuscript, pdfs);
      await startPipeline(session.id);
      router.push(`/verify/${session.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start session");
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8 max-w-2xl mx-auto">
      <div className="text-center space-y-2">
        <h2 className="text-2xl font-semibold">Verify Your References</h2>
        <p className="text-muted-foreground">
          Upload your manuscript and reference PDFs to begin automated verification.
        </p>
      </div>

      <UploadZone
        accept=".docx"
        label="Drop your manuscript here"
        sublabel=".docx files only"
        onFilesSelected={(files) => setManuscript(files[0] ?? null)}
      />

      {manuscript && (
        <div className="flex items-center gap-2">
          <Badge variant="secondary">{manuscript.name}</Badge>
          <button
            onClick={() => setManuscript(null)}
            className="text-xs text-muted-foreground hover:text-destructive"
          >
            Remove
          </button>
        </div>
      )}

      <UploadZone
        accept=".pdf"
        multiple
        label="Drop reference PDFs here"
        sublabel="Optional — we&apos;ll try to find papers automatically"
        onFilesSelected={(files) => setPdfs((prev) => [...prev, ...files])}
      />

      {pdfs.length > 0 && (
        <div className="space-y-1">
          <p className="text-sm text-muted-foreground">
            {pdfs.length} PDF{pdfs.length > 1 ? "s" : ""} selected
          </p>
          <div className="flex flex-wrap gap-1">
            {pdfs.slice(0, 5).map((f, i) => (
              <Badge key={i} variant="outline" className="text-xs">
                {f.name}
              </Badge>
            ))}
            {pdfs.length > 5 && (
              <Badge variant="outline" className="text-xs">
                +{pdfs.length - 5} more
              </Badge>
            )}
          </div>
        </div>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}

      <Button
        size="lg"
        className="w-full"
        disabled={!manuscript || loading}
        onClick={handleStart}
      >
        {loading ? "Starting..." : "Start Verification"}
      </Button>
    </div>
  );
}
