"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
} from "recharts";
import { apiFetch } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { useRealtimeEvents } from "@/lib/ws";
import { useTheme } from "@/components/theme";
import type { Machine, MachineStatus, Metric } from "@/lib/types";

// ── Types ──────────────────────────────────────────────────────────────────

const RANGES = ["1h", "6h", "24h", "7d"] as const;
type Range = (typeof RANGES)[number];

type ChartPoint = {
  t: string;
  cpu: number;
  mem: number;
  disk: number;
};

// ── Sub-components ─────────────────────────────────────────────────────────

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

function MetricChart({
  data,
  dataKey,
  label,
  color,
}: {
  data: ChartPoint[];
  dataKey: keyof Omit<ChartPoint, "t">;
  label: string;
  color: string;
}) {
  const { isDark } = useTheme();
  const grid = isDark ? "#1e293b" : "#e2e8f0";
  const tick = isDark ? "#64748b" : "#94a3b8";
  const tooltipBg = isDark ? "#1e293b" : "#ffffff";
  const tooltipBorder = isDark ? "#334155" : "#e2e8f0";
  const tooltipLabel = isDark ? "#94a3b8" : "#475569";

  const latest = data.length > 0 ? data[data.length - 1][dataKey] : null;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs dark:border-slate-700/50 dark:bg-slate-800/40 dark:shadow-none">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{label}</span>
        {latest !== null && (
          <span className="text-sm font-semibold" style={{ color }}>
            {latest}%
          </span>
        )}
      </div>

      {data.length === 0 ? (
        <div className="flex h-24 items-center justify-center text-xs text-slate-400 dark:text-slate-600">
          Aucune donnée
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={120}>
          <LineChart data={data} margin={{ top: 2, right: 4, bottom: 0, left: -22 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={grid} />
            <XAxis
              dataKey="t"
              tick={{ fontSize: 10, fill: tick }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fontSize: 10, fill: tick }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{
                background: tooltipBg,
                border: `1px solid ${tooltipBorder}`,
                borderRadius: "0.5rem",
                fontSize: 11,
              }}
              labelStyle={{ color: tooltipLabel }}
              formatter={(value: number) => [`${value}%`, label]}
            />
            <Line
              type="monotone"
              dataKey={dataKey}
              stroke={color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 3 }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function MachinePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const token = getToken() ?? "";
  const qc = useQueryClient();
  const [range, setRange] = useState<Range>("1h");

  const { data: machine } = useQuery<Machine>({
    queryKey: ["machine", id],
    queryFn: () => apiFetch<Machine>(`/machines/${id}`, token),
    refetchInterval: 30_000,
  });

  const { data: metrics = [] } = useQuery<Metric[]>({
    queryKey: ["metrics", id, range],
    queryFn: () =>
      apiFetch<Metric[]>(`/machines/${id}/metrics?range=${range}`, token),
    refetchInterval: 15_000,
  });

  // Refresh on any event targeting this machine
  useRealtimeEvents((e) => {
    if (e.machine_id === Number(id)) {
      qc.invalidateQueries({ queryKey: ["machine", id] });
      qc.invalidateQueries({ queryKey: ["metrics", id] });
    }
  });

  const chartData: ChartPoint[] = metrics.map((m) => ({
    t: new Date(m.time).toLocaleTimeString("fr-FR", {
      hour: "2-digit",
      minute: "2-digit",
    }),
    cpu: +m.cpu_pct.toFixed(1),
    mem: +m.mem_pct.toFixed(1),
    disk: +m.disk_pct.toFixed(1),
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => router.push("/dashboard")}
          className="text-sm text-slate-500 transition-colors hover:text-slate-700 dark:hover:text-slate-300"
        >
          ← Retour
        </button>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
          {machine?.name ?? "…"}
        </h1>
        {machine && <StatusBadge status={machine.status} />}
      </div>

      {/* Meta */}
      {machine && (
        <div className="flex flex-wrap gap-4 text-sm text-slate-600 dark:text-slate-400">
          {machine.hostname && <span>{machine.hostname}</span>}
          {machine.os && <span>{machine.os}</span>}
          {machine.agent_version && (
            <span className="text-slate-400 dark:text-slate-600">v{machine.agent_version}</span>
          )}
          {machine.last_seen_at && (
            <span className="ml-auto text-xs text-slate-500">
              Vu le{" "}
              {new Date(machine.last_seen_at).toLocaleString("fr-FR")}
            </span>
          )}
        </div>
      )}

      {/* Range selector */}
      <div className="flex gap-2">
        {RANGES.map((r) => (
          <button
            key={r}
            onClick={() => setRange(r)}
            className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
              range === r
                ? "bg-sky-600 text-white"
                : "bg-slate-200 text-slate-600 hover:bg-slate-300 hover:text-slate-900 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-slate-200"
            }`}
          >
            {r}
          </button>
        ))}
      </div>

      {/* Charts */}
      <div className="space-y-4">
        <MetricChart data={chartData} dataKey="cpu" label="CPU" color="#38bdf8" />
        <MetricChart data={chartData} dataKey="mem" label="RAM" color="#a78bfa" />
        <MetricChart data={chartData} dataKey="disk" label="Disque" color="#fb923c" />
      </div>
    </div>
  );
}
