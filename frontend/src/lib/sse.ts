/** SSE connection manager with reconnect support. */

import type { PipelineEvent } from "./types";

export function connectSSE(
  url: string,
  onEvent: (event: PipelineEvent) => void,
  onError?: () => void
): () => void {
  let closed = false;
  let eventSource: EventSource | null = null;

  function connect() {
    if (closed) return;
    eventSource = new EventSource(url);

    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as PipelineEvent;
        // Only process events that have a meaningful stage or status
        if (data.stage !== undefined || data.status) {
          onEvent(data);
        }
      } catch {
        // Ignore keepalive `{}` or malformed events
      }
    };

    eventSource.onerror = () => {
      if (closed) return;
      eventSource?.close();
      onError?.();
      // Auto-reconnect after 2 seconds
      setTimeout(connect, 2000);
    };
  }

  connect();

  return () => {
    closed = true;
    eventSource?.close();
  };
}
