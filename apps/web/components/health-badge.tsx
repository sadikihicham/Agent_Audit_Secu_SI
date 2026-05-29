"use client";

import { useEffect, useState } from "react";

type State = "loading" | "ok" | "error";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8800";

export function HealthBadge() {
  const [state, setState] = useState<State>("loading");
  const [detail, setDetail] = useState<string>("Vérification…");

  useEffect(() => {
    let active = true;
    fetch(`${API_URL}/health`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => {
        if (!active) return;
        setState("ok");
        setDetail(`${data.service} · ${data.status}`);
      })
      .catch(() => {
        if (!active) return;
        setState("error");
        setDetail(`API injoignable (${API_URL})`);
      });
    return () => {
      active = false;
    };
  }, []);

  const color =
    state === "ok"
      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
      : state === "error"
        ? "bg-rose-500/15 text-rose-300 border-rose-500/30"
        : "bg-slate-500/15 text-slate-300 border-slate-500/30";

  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm ${color}`}
    >
      <span className="h-2 w-2 rounded-full bg-current" />
      {detail}
    </span>
  );
}
