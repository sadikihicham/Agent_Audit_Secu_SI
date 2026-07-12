"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { useRealtimeEvents } from "@/lib/ws";
import type { Machine, MachineStatus } from "@/lib/types";

const STATUS_STYLES: Record<MachineStatus, string> = {
  online: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  offline: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  unknown: "bg-slate-500/15 text-slate-400 border-slate-500/30",
};
const STATUS_LABELS: Record<MachineStatus, string> = {
  online: "En ligne",
  offline: "Hors ligne",
  unknown: "Inconnu",
};

function StatusBadge({ status }: { status: MachineStatus }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs ${STATUS_STYLES[status]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {STATUS_LABELS[status]}
    </span>
  );
}

export default function DashboardPage() {
  const token = getToken() ?? "";
  const qc = useQueryClient();

  const { data: machines = [], isLoading } = useQuery<Machine[]>({
    queryKey: ["machines"],
    queryFn: () => apiFetch<Machine[]>("/machines", token),
    refetchInterval: 30_000,
  });

  // Invalidate machine list whenever any alert fires (status may have changed)
  useRealtimeEvents(() => {
    qc.invalidateQueries({ queryKey: ["machines"] });
  });

  const online = machines.filter((m) => m.status === "online").length;
  const offline = machines.filter((m) => m.status === "offline").length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Vue globale du parc
        </h1>
        <span className="text-xs text-slate-500">
          {machines.length} machine{machines.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Summary pills */}
      {machines.length > 0 && (
        <div className="flex gap-3">
          <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-300">
            {online} en ligne
          </span>
          {offline > 0 && (
            <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-3 py-1 text-xs text-rose-300">
              {offline} hors ligne
            </span>
          )}
        </div>
      )}

      {/* Machine grid */}
      {isLoading ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : machines.length === 0 ? (
        <p className="text-sm text-slate-500">Aucune machine enregistrée.</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {machines.map((m) => (
            <Link
              key={m.id}
              href={`/machines/${m.id}`}
              className="group rounded-xl border border-slate-200 bg-white p-4 shadow-xs transition-all hover:border-sky-400 hover:shadow dark:border-slate-700/50 dark:bg-slate-800/40 dark:shadow-none dark:hover:border-sky-600/50 dark:hover:bg-slate-800/70"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-900 dark:text-slate-100">
                    {m.name}
                  </p>
                  <p className="mt-0.5 truncate text-xs text-slate-500">
                    {m.hostname ?? "—"}
                  </p>
                </div>
                <StatusBadge status={m.status} />
              </div>

              <div className="mt-3 flex items-center gap-3 text-xs text-slate-500">
                <span>{m.os ?? "—"}</span>
                {m.last_seen_at && (
                  <span className="ml-auto">
                    {new Date(m.last_seen_at).toLocaleTimeString("fr-FR")}
                  </span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
