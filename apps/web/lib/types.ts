export type MachineStatus = "online" | "offline" | "unknown";

export type Machine = {
  id: number;
  name: string;
  hostname: string | null;
  os: string | null;
  agent_version: string | null;
  last_seen_at: string | null;
  status: MachineStatus;
  created_at: string;
};

export type Metric = {
  machine_id: number;
  time: string;
  cpu_pct: number;
  mem_pct: number;
  disk_pct: number;
  uptime_s: number;
};

export type AlertSeverity = "warning" | "critical";
export type AlertStatus = "open" | "resolved";

export type Alert = {
  id: number;
  machine_id: number;
  type: string;
  severity: AlertSeverity;
  message: string;
  value: number | null;
  threshold: number | null;
  status: AlertStatus;
  created_at: string;
  resolved_at: string | null;
};

export type RealtimeEvent = {
  event: "alert.created" | "alert.resolved";
  machine_id: number;
  type: string;
  severity?: string;
};
