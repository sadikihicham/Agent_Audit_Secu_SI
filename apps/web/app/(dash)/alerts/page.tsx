"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { useRealtimeEvents } from "@/lib/ws";
import type { Alert, AlertSeverity, AlertStatus } from "@/lib/types";

// ── Badges ─────────────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: AlertSeverity }) {
  const styles: Record<AlertSeverity, string> = {
    warning: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    critical: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  };
  const labels: Record<AlertSeverity, string> = {
    warning: "Warning",
    critical: "Critique",
  };
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 text-xs ${styles[severity]}`}
    >
      {labels[severity]}
    </span>
  );
}

function StatusPill({ status }: { status: AlertStatus }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
        status === "open"
          ? "bg-rose-500/15 text-rose-300"
          : "bg-slate-700/60 text-slate-400"
      }`}
    >
      {status === "open" ? "Ouverte" : "Résolue"}
    </span>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

const FILTERS = ["open", "resolved", "all"] as const;
type Filter = (typeof FILTERS)[number];
const FILTER_LABELS: Record<Filter, string> = {
  open: "Ouvertes",
  resolved: "Résolues",
  all: "Toutes",
};

export default function AlertsPage() {
  const token = getToken() ?? "";
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("open");

  const url =
    filter === "all" ? "/alerts" : `/alerts?status=${filter}`;

  const { data: alerts = [], isLoading } = useQuery<Alert[]>({
    queryKey: ["alerts", filter],
    queryFn: () => apiFetch<Alert[]>(url, token),
    refetchInterval: 30_000,
  });

  useRealtimeEvents(() => {
    qc.invalidateQueries({ queryKey: ["alerts"] });
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-100">Alertes</h1>

        <div className="flex gap-2">
          {FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                filter === f
                  ? "bg-sky-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
              }`}
            >
              {FILTER_LABELS[f]}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      {isLoading ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : alerts.length === 0 ? (
        <p className="text-sm text-slate-500">Aucune alerte.</p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-700/50">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-800/60">
                {["Type", "Machine", "Sévérité", "Message", "Valeur", "Statut", "Créée"].map(
                  (h) => (
                    <th
                      key={h}
                      className="px-4 py-3 text-left text-xs font-medium text-slate-400"
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/30">
              {alerts.map((a) => (
                <tr key={a.id} className="hover:bg-slate-800/30">
                  <td className="px-4 py-3 font-mono text-xs text-slate-300">
                    {a.type}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-400">
                    #{a.machine_id}
                  </td>
                  <td className="px-4 py-3">
                    <SeverityBadge severity={a.severity} />
                  </td>
                  <td className="max-w-xs truncate px-4 py-3 text-xs text-slate-400">
                    {a.message}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {a.value != null ? `${a.value.toFixed(1)}%` : "—"}
                    {a.threshold != null
                      ? ` / seuil ${a.threshold}%`
                      : ""}
                  </td>
                  <td className="px-4 py-3">
                    <StatusPill status={a.status} />
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {new Date(a.created_at).toLocaleString("fr-FR")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
