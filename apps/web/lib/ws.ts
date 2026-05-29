"use client";

import { useEffect, useRef } from "react";
import { fetchWsTicket } from "./api";
import { getToken } from "./auth";
import type { RealtimeEvent } from "./types";

const WS_BASE = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8800"
).replace(/^http/, "ws");

/**
 * Ouvre un WebSocket temps réel en utilisant un ticket à usage unique obtenu
 * via POST /ws/ticket (le JWT ne transite jamais dans une URL).
 */
export function useRealtimeEvents(
  onEvent: (e: RealtimeEvent) => void,
): void {
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    const token = getToken();
    if (!token) return;

    let ws: WebSocket | null = null;
    let cancelled = false;

    // Étape 1 : obtenir un ticket opaque court-vécu.
    fetchWsTicket(token)
      .then((ticket) => {
        if (cancelled) return;

        // Étape 2 : ouvrir le WebSocket avec le ticket (pas le JWT).
        ws = new WebSocket(`${WS_BASE}/ws?ticket=${ticket}`);

        ws.onmessage = (ev) => {
          try {
            cbRef.current(JSON.parse(ev.data) as RealtimeEvent);
          } catch {
            // ignore malformed messages
          }
        };

        ws.onerror = () => {
          // silently ignore — ws.onclose will fire after
        };
      })
      .catch(() => {
        // apiFetch already redirects to /login on 401
      });

    return () => {
      cancelled = true;
      ws?.close();
    };
  }, []);
}
