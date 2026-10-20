"use client";

import { useEffect, useRef } from "react";

import { apiUrl, authHeader } from "./backend";
import { readBearer } from "./bearer";
import { parseFrames } from "./sse";

/**
 * Subscribe to a Session's SSE stream.
 *
 * `EventSource` is not usable here: it cannot send an `Authorization`
 * header, and the backend requires a bearer. So this reads the response
 * body as a stream and folds it through `parseFrames`.
 *
 * Reconnects are resumable — the last `id` seen goes back as
 * `last_event_id`, so the server replays only what was missed. Reconnect
 * is deliberately unbounded-but-slow (2s): a Session with nothing left to
 * report simply parks, which is the expected state between issues, and a
 * reconnect storm would be worse than a quiet connection.
 *
 * The replay the reconnect asks for is served from the backend's
 * in-process event log, so it covers dropped connections but not a
 * restarted server (issue #9 makes it durable).
 */

const RECONNECT_MS = 2000;

export type ServerEvent = {
  id: number | null;
  event: string;
  data: Record<string, unknown>;
};

export function useSessionEvents(
  sessionId: string | null,
  onEvent: (event: ServerEvent) => void,
): void {
  // Keep the latest handler without re-opening the stream every render.
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    let cancelled = false;
    let lastEventId = 0;
    let rest = "";
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = async () => {
      // A signed-out user is not an error here — the dashboard sends them
      // to /login — so this parks quietly instead of retrying forever.
      if (!readBearer()) return;
      const url = apiUrl(`/sessions/${sessionId}/events?last_event_id=${lastEventId}`);

      try {
        const res = await fetch(url, {
          headers: authHeader(),
          signal: controller.signal,
        });
        if (!res.ok || !res.body) throw new Error(`stream failed: ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          const { frames, rest: tail } = parseFrames(rest + decoder.decode(value, { stream: true }));
          rest = tail;
          for (const frame of frames) {
            if (frame.id !== null) lastEventId = Number(frame.id) || lastEventId;
            handler.current({
              id: frame.id === null ? null : Number(frame.id),
              event: frame.event,
              data: parseData(frame.data),
            });
          }
        }
      } catch (err) {
        // An abort is the normal unmount path, not a failure worth logging.
        if (controller.signal.aborted) return;
        console.warn("session event stream ended:", err);
      }

      if (!cancelled && !controller.signal.aborted) {
        timer = setTimeout(connect, RECONNECT_MS);
      }
    };

    void connect();

    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [sessionId]);
}

function parseData(raw: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(raw) as unknown;
    return typeof parsed === "object" && parsed !== null
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}