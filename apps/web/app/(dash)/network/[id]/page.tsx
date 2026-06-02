"use client";

import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { getToken } from "@/lib/auth";
import {
  DeviceStatusBadge,
  DeviceRiskBadge,
  DeviceTypeIcon,
  VulnSeverityBadge,
  deviceTypeLabel,
  eventKindLabel,
} from "@/components/network-state";
import type {
  Device,
  DeviceInterface,
  DevicePort,
  DeviceStatus,
  NetworkEventItem,
  Vuln,
} from "@/lib/types";

// ── Formateurs SNMP ───────────────────────────────────────────────────────────

function formatUptime(secs: number): string {
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (d > 0) return `${d} j ${h} h`;
  if (h > 0) return `${h} h ${m} min`;
  return `${m} min`;
}

function formatBytes(n: number): string {
  if (n <= 0) return "0 o";
  const units = ["o", "Ko", "Mo", "Go", "To", "Po"];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), units.length - 1);
  return `${(n / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatSpeed(bps: number): string {
  if (bps <= 0) return "—";
  const units = ["bit/s", "Kbit/s", "Mbit/s", "Gbit/s", "Tbit/s"];
  const i = Math.min(Math.floor(Math.log(bps) / Math.log(1000)), units.length - 1);
  return `${(bps / 1000 ** i).toFixed(i <= 1 ? 0 : 1)} ${units[i]}`;
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700/50 dark:bg-slate-800/40 dark:shadow-none">
      <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
      <p className={`mt-1 text-sm text-slate-900 dark:text-slate-100 ${mono ? "font-mono" : ""}`}>
        {value}
      </p>
    </div>
  );
}

export default function DevicePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const token = getToken() ?? "";

  const { data: device, isLoading } = useQuery<Device>({
    queryKey: ["device", id],
    queryFn: () => apiFetch<Device>(`/network/devices/${id}`, token),
    refetchInterval: 30_000,
  });

  const { data: ports = [] } = useQuery<DevicePort[]>({
    queryKey: ["device-ports", id],
    queryFn: () => apiFetch<DevicePort[]>(`/network/devices/${id}/ports`, token),
    refetchInterval: 30_000,
  });

  const { data: vulns = [] } = useQuery<Vuln[]>({
    queryKey: ["device-vulns", id],
    queryFn: () => apiFetch<Vuln[]>(`/network/devices/${id}/vulns`, token),
    refetchInterval: 30_000,
  });

  const { data: events = [] } = useQuery<NetworkEventItem[]>({
    queryKey: ["device-events", id],
    queryFn: () =>
      apiFetch<NetworkEventItem[]>(`/network/events?device_id=${id}&limit=50`, token),
    refetchInterval: 30_000,
  });

  const { data: interfaces = [] } = useQuery<DeviceInterface[]>({
    queryKey: ["device-interfaces", id],
    queryFn: () =>
      apiFetch<DeviceInterface[]>(`/network/devices/${id}/interfaces`, token),
    refetchInterval: 30_000,
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => router.push("/network")}
          className="text-sm text-slate-500 transition-colors hover:text-slate-700 dark:hover:text-slate-300"
        >
          ← Retour
        </button>
        {device && <DeviceTypeIcon type={device.device_type} size="lg" />}
        <div>
          <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
            {device?.hostname ?? device?.ip ?? "…"}
          </h1>
          {device && (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {deviceTypeLabel(device.device_type)}
            </p>
          )}
        </div>
        {device && <DeviceStatusBadge status={device.status as DeviceStatus} />}
        {device && <DeviceRiskBadge risk={device.risk} />}
        {device?.is_gateway && (
          <span className="rounded bg-sky-500/15 px-2 py-0.5 text-xs text-sky-600 dark:text-sky-300">
            passerelle
          </span>
        )}
        {device?.snmp_reachable && (
          <span className="rounded bg-violet-500/15 px-2 py-0.5 text-xs text-violet-600 dark:text-violet-300">
            SNMP
          </span>
        )}
      </div>

      {isLoading || !device ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : (
        <>
          {/* Identité */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Adresse IP" value={device.ip} mono />
            <Field label="Adresse MAC" value={device.mac ?? "—"} mono />
            <Field label="Nom d'hôte" value={device.hostname ?? "—"} />
            <Field label="Type" value={deviceTypeLabel(device.device_type)} />
            <Field label="Système (estimé)" value={device.os_guess ?? "—"} />
            <Field label="Constructeur" value={device.vendor ?? "—"} />
            <Field label="Découvert par (agent)" value={`#${device.discovered_by_machine_id}`} />
            <Field
              label="Première détection"
              value={new Date(device.first_seen_at).toLocaleString("fr-FR")}
            />
            <Field
              label="Dernière détection"
              value={new Date(device.last_seen_at).toLocaleString("fr-FR")}
            />
            {device.snmp_reachable && (
              <>
                <Field
                  label="Uptime (SNMP)"
                  value={
                    device.sys_uptime_secs != null
                      ? formatUptime(device.sys_uptime_secs)
                      : "—"
                  }
                />
                <Field label="Emplacement (SNMP)" value={device.sys_location ?? "—"} />
                <Field label="Contact (SNMP)" value={device.sys_contact ?? "—"} />
              </>
            )}
          </div>

          {/* Vulnérabilités */}
          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              Vulnérabilités{" "}
              <span className="text-slate-400">({vulns.length})</span>
            </h2>
            {vulns.length === 0 ? (
              <p className="text-sm text-slate-500">Aucune vulnérabilité détectée.</p>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700/50">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-100 dark:border-slate-700/50 dark:bg-slate-800/60">
                      {["Sévérité", "CVE", "Titre", "CVSS", "Port", "Source"].map((h) => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-700/30">
                    {vulns.map((v) => (
                      <tr key={v.id} className="bg-white hover:bg-slate-50 dark:bg-transparent dark:hover:bg-slate-800/30">
                        <td className="px-4 py-3"><VulnSeverityBadge severity={v.severity} /></td>
                        <td className="px-4 py-3 font-mono text-xs text-slate-600 dark:text-slate-400">
                          {v.cve_id ?? "—"}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-700 dark:text-slate-300">
                          <div>{v.title}</div>
                          {v.description && (
                            <div className="mt-0.5 text-slate-400">{v.description}</div>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">{v.cvss ?? "—"}</td>
                        <td className="px-4 py-3 font-mono text-xs text-slate-500">
                          {ports.find((p) => p.id === v.port_id)?.port ?? "—"}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-400">
                          {v.source === "cve-db" ? "Base CVE" : "Règle"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Ports ouverts */}
          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              Ports ouverts <span className="text-slate-400">({ports.length})</span>
            </h2>
            {ports.length === 0 ? (
              <p className="text-sm text-slate-500">Aucun port ouvert détecté.</p>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700/50">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-100 dark:border-slate-700/50 dark:bg-slate-800/60">
                      {["Port", "Proto", "Service", "Version", "Bannière"].map((h) => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-700/30">
                    {ports.map((p) => (
                      <tr key={p.id} className="bg-white hover:bg-slate-50 dark:bg-transparent dark:hover:bg-slate-800/30">
                        <td className="px-4 py-3 font-mono text-xs text-slate-700 dark:text-slate-300">{p.port}</td>
                        <td className="px-4 py-3 text-xs text-slate-500">{p.protocol}</td>
                        <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-400">{p.service_name ?? "—"}</td>
                        <td className="px-4 py-3 text-xs text-slate-500">{p.service_version ?? "—"}</td>
                        <td className="max-w-md truncate px-4 py-3 font-mono text-[11px] text-slate-400">
                          {p.banner ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Interfaces réseau (SNMP) */}
          {interfaces.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                Interfaces réseau{" "}
                <span className="text-slate-400">({interfaces.length})</span>
                <span className="ml-2 rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] font-normal text-violet-600 dark:text-violet-300">
                  SNMP
                </span>
              </h2>
              <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700/50">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-100 dark:border-slate-700/50 dark:bg-slate-800/60">
                      {["#", "Nom", "MAC", "Statut", "Débit", "MTU", "Entrant", "Sortant"].map(
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
                    {interfaces.map((it) => (
                      <tr
                        key={it.id}
                        className="bg-white hover:bg-slate-50 dark:bg-transparent dark:hover:bg-slate-800/30"
                      >
                        <td className="px-4 py-3 font-mono text-xs text-slate-500">{it.if_index}</td>
                        <td className="px-4 py-3 text-xs text-slate-700 dark:text-slate-300">
                          {it.name ?? "—"}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs text-slate-500">{it.mac ?? "—"}</td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs ${
                              it.oper_up
                                ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300"
                                : "bg-slate-500/15 text-slate-500 dark:text-slate-400"
                            }`}
                          >
                            <span className="h-1.5 w-1.5 rounded-full bg-current" />
                            {it.oper_up ? "up" : "down"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">
                          {it.speed_bps != null ? formatSpeed(it.speed_bps) : "—"}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">{it.mtu ?? "—"}</td>
                        <td className="px-4 py-3 text-xs text-slate-500">
                          {it.in_octets != null ? formatBytes(it.in_octets) : "—"}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">
                          {it.out_octets != null ? formatBytes(it.out_octets) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Événements récents */}
          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              Événements récents <span className="text-slate-400">({events.length})</span>
            </h2>
            {events.length === 0 ? (
              <p className="text-sm text-slate-500">Aucun événement pour cet appareil.</p>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700/50">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-100 dark:border-slate-700/50 dark:bg-slate-800/60">
                      {["Sévérité", "Type", "Message", "Quand"].map((h) => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-700/30">
                    {events.map((e) => (
                      <tr key={e.id} className="bg-white hover:bg-slate-50 dark:bg-transparent dark:hover:bg-slate-800/30">
                        <td className="px-4 py-3"><VulnSeverityBadge severity={e.severity} /></td>
                        <td className="px-4 py-3 text-xs font-medium text-slate-700 dark:text-slate-300">
                          {eventKindLabel(e.kind)}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-400">{e.message}</td>
                        <td className="px-4 py-3 text-xs text-slate-500">
                          {new Date(e.created_at).toLocaleString("fr-FR")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
