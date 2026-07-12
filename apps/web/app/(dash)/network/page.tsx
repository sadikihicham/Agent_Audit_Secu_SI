"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { useRealtimeEvents } from "@/lib/ws";
import {
  NetworkStateBadge,
  NETWORK_STATE_META,
  DeviceStatusBadge,
  DeviceRiskBadge,
  DeviceTypeIcon,
  deviceTypeLabel,
} from "@/components/network-state";
import type { Device, DeviceStatus, NetworkSummary } from "@/lib/types";

// ── KPI ──────────────────────────────────────────────────────────────────────

function Kpi({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs dark:border-slate-700/50 dark:bg-slate-800/40 dark:shadow-none">
      <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${accent ?? "text-slate-900 dark:text-slate-100"}`}>
        {value}
      </p>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

const STATUS_FILTERS = ["all", "up", "down"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];
const STATUS_FILTER_LABELS: Record<StatusFilter, string> = {
  all: "Tous",
  up: "Actifs",
  down: "Hors-ligne",
};

export default function NetworkPage() {
  const token = getToken() ?? "";
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [typeFilter, setTypeFilter] = useState<string>("all");

  const { data: summary } = useQuery<NetworkSummary>({
    queryKey: ["network-summary"],
    queryFn: () => apiFetch<NetworkSummary>("/network/summary", token),
    refetchInterval: 30_000,
  });

  const params = new URLSearchParams();
  if (statusFilter !== "all") params.set("status", statusFilter);
  if (typeFilter !== "all") params.set("type", typeFilter);
  const devicesUrl = `/network/devices${params.toString() ? `?${params}` : ""}`;

  const { data: devices = [], isLoading } = useQuery<Device[]>({
    queryKey: ["network-devices", statusFilter, typeFilter],
    queryFn: () => apiFetch<Device[]>(devicesUrl, token),
    refetchInterval: 30_000,
  });

  useRealtimeEvents(() => {
    qc.invalidateQueries({ queryKey: ["network-summary"] });
    qc.invalidateQueries({ queryKey: ["network-devices"] });
  });

  const types = summary ? Object.keys(summary.by_type).sort() : [];

  return (
    <div className="space-y-6">
      {/* Header + état global */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">Réseau</h1>
          {summary && <NetworkStateBadge state={summary.state} size="lg" />}
        </div>
        <div className="flex items-center gap-4">
          <Link
            href="/network/vulns"
            className="rounded-lg border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition-colors hover:border-sky-400 hover:text-sky-600 dark:border-slate-700 dark:text-slate-300 dark:hover:border-sky-600 dark:hover:text-sky-400"
          >
            Vulnérabilités →
          </Link>
          <Link
            href="/network/events"
            className="rounded-lg border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition-colors hover:border-sky-400 hover:text-sky-600 dark:border-slate-700 dark:text-slate-300 dark:hover:border-sky-600 dark:hover:text-sky-400"
          >
            Intrusions →
          </Link>
          {summary?.last_scan_at && (
            <span className="text-xs text-slate-500">
              Dernier scan : {new Date(summary.last_scan_at).toLocaleString("fr-FR")}
            </span>
          )}
        </div>
      </div>

      {/* Raisons de l'état */}
      {summary && summary.reasons.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {summary.reasons.map((r, i) => (
            <span
              key={i}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs ${NETWORK_STATE_META[r.state].badge}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${NETWORK_STATE_META[r.state].dot}`} />
              {r.label}
              <span className="font-semibold">· {r.count}</span>
            </span>
          ))}
        </div>
      )}

      {/* KPIs */}
      {summary && (
        <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Kpi label="Appareils" value={summary.total} />
          <Kpi label="Actifs" value={summary.up} accent="text-emerald-600 dark:text-emerald-400" />
          <Kpi label="Hors-ligne" value={summary.down} accent="text-rose-600 dark:text-rose-400" />
          <Kpi label="Passerelles" value={summary.gateways} />
          <Kpi label="Nouveaux (24 h)" value={summary.new_last_window} accent="text-sky-600 dark:text-sky-400" />
          <Kpi
            label="Intrusions (1 h)"
            value={summary.events_recent}
            accent={summary.events_recent > 0 ? "text-amber-600 dark:text-amber-400" : undefined}
          />
        </div>
      )}

      {/* Filtres */}
      <div className="flex flex-wrap items-center gap-2">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setStatusFilter(f)}
            className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
              statusFilter === f
                ? "bg-sky-600 text-white"
                : "bg-slate-200 text-slate-600 hover:bg-slate-300 hover:text-slate-900 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-slate-200"
            }`}
          >
            {STATUS_FILTER_LABELS[f]}
          </button>
        ))}
        <span className="mx-1 h-4 w-px bg-slate-300 dark:bg-slate-700" />
        <button
          onClick={() => setTypeFilter("all")}
          className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
            typeFilter === "all"
              ? "bg-sky-600 text-white"
              : "bg-slate-200 text-slate-600 hover:bg-slate-300 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700"
          }`}
        >
          Tout type
        </button>
        {types.map((t) => (
          <button
            key={t}
            onClick={() => setTypeFilter(t)}
            className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
              typeFilter === t
                ? "bg-sky-600 text-white"
                : "bg-slate-200 text-slate-600 hover:bg-slate-300 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700"
            }`}
          >
            {deviceTypeLabel(t)}
          </button>
        ))}
      </div>

      {/* Tableau */}
      {isLoading ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : devices.length === 0 ? (
        <p className="text-sm text-slate-500">
          Aucun appareil découvert. Activez le scan dans l&apos;agent (section{" "}
          <code className="font-mono">[scan]</code> d&apos;agent.toml).
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700/50">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-100 dark:border-slate-700/50 dark:bg-slate-800/60">
                {["Nom", "IP", "MAC", "Type", "Constructeur", "OS", "Statut", "Risque", "Ports", "Vulns", "Vu le"].map(
                  (h) => (
                    <th
                      key={h}
                      className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400"
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700/30">
              {devices.map((d) => (
                <tr
                  key={d.id}
                  className="bg-white hover:bg-slate-50 dark:bg-transparent dark:hover:bg-slate-800/30"
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <DeviceTypeIcon type={d.device_type} size="sm" />
                      <div className="min-w-0">
                        <Link
                          href={`/network/${d.id}`}
                          className="font-medium text-slate-900 hover:text-sky-600 dark:text-slate-100 dark:hover:text-sky-400"
                        >
                          {d.hostname ?? "—"}
                        </Link>
                        {d.is_gateway && (
                          <span className="ml-2 rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] text-sky-600 dark:text-sky-300">
                            passerelle
                          </span>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-700 dark:text-slate-300">{d.ip}</td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">{d.mac ?? "—"}</td>
                  <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-400">
                    {deviceTypeLabel(d.device_type)}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">{d.vendor ?? "—"}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">{d.os_guess ?? "—"}</td>
                  <td className="px-4 py-3">
                    <DeviceStatusBadge status={d.status as DeviceStatus} />
                  </td>
                  <td className="px-4 py-3">
                    <DeviceRiskBadge risk={d.risk} />
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">{d.open_ports}</td>
                  <td className="px-4 py-3 text-xs">
                    {d.vuln_count > 0 ? (
                      <span className="font-medium text-rose-600 dark:text-rose-400">
                        {d.vuln_count}
                      </span>
                    ) : (
                      <span className="text-slate-400">0</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {new Date(d.last_seen_at).toLocaleString("fr-FR")}
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
