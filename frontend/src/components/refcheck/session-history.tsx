"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { listSessions, deleteSession, startPipeline } from "@/lib/api";
import type { Session } from "@/lib/types";

const STATUS_COLORS: Record<string, string> = {
  created: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  running: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  paused: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  complete: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  error: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
};

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function SessionHistory() {
  const router = useRouter();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const perPage = 10;

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSessions(page, perPage);
      setSessions(data.sessions);
      setTotal(data.total);
    } catch {
      /* session list is best-effort */
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const handleDelete = async (id: string) => {
    if (!confirm(`Delete session ${id}? This cannot be undone.`)) return;
    setDeletingId(id);
    try {
      await deleteSession(id);
      await fetchSessions();
    } catch {
      /* ignore delete errors */
    } finally {
      setDeletingId(null);
    }
  };

  const handleResume = async (session: Session) => {
    if (session.status === "created") {
      try {
        await startPipeline(session.id);
      } catch {
        /* ignore start errors — navigate anyway */
      }
    }
    router.push(`/verify/${session.id}`);
  };

  if (loading && sessions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-4">
        Loading sessions...
      </p>
    );
  }

  if (total === 0) {
    return null;
  }

  const totalPages = Math.ceil(total / perPage);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">Recent Sessions</h3>
        <span className="text-sm text-muted-foreground">
          {total} session{total !== 1 ? "s" : ""}
        </span>
      </div>

      <div className="space-y-2">
        {sessions.map((s) => (
          <Card key={s.id} className="p-4">
            <div className="flex items-center justify-between gap-4">
              <div className="flex-1 min-w-0 space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm truncate">
                    {s.manuscript_filename}
                  </span>
                  <Badge
                    variant="secondary"
                    className={STATUS_COLORS[s.status] ?? ""}
                  >
                    {s.status}
                  </Badge>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span>{formatDate(s.created_at)}</span>
                  <span>{s.pdf_count} PDF{s.pdf_count !== 1 ? "s" : ""}</span>
                  <span className="font-mono">{s.id}</span>
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {(s.status === "complete" || s.status === "running") && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => router.push(`/verify/${s.id}`)}
                  >
                    View
                  </Button>
                )}
                {(s.status === "created" || s.status === "paused" || s.status === "error") && (
                  <Button
                    variant="default"
                    size="sm"
                    onClick={() => handleResume(s)}
                  >
                    {s.status === "created" ? "Start" : "Resume"}
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => handleDelete(s.id)}
                  disabled={deletingId === s.id}
                >
                  {deletingId === s.id ? "..." : "Delete"}
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
