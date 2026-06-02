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

export type RealtimeEvent =
  | {
      event: "alert.created" | "alert.resolved";
      machine_id: number;
      type: string;
      severity?: string;
    }
  | {
      event: "network.event";
      kind: string;
      severity: string;
      machine_id: number;
    };

// ── Réseau ───────────────────────────────────────────────────────────────────

export type DeviceStatus = "up" | "down" | "unknown";
export type DeviceRisk = "safe" | "vulnerable" | "critical";

export type Device = {
  id: number;
  discovered_by_machine_id: number;
  ip: string;
  mac: string | null;
  hostname: string | null;
  vendor: string | null;
  device_type: string;
  os_guess: string | null;
  is_gateway: boolean;
  status: DeviceStatus;
  first_seen_at: string;
  last_seen_at: string;
  snmp_reachable: boolean;
  sys_descr: string | null;
  sys_uptime_secs: number | null;
  sys_location: string | null;
  sys_contact: string | null;
  risk: DeviceRisk;
  open_ports: number;
  vuln_count: number;
};

export type DeviceInterface = {
  id: number;
  device_id: number;
  if_index: number;
  name: string | null;
  mac: string | null;
  admin_up: boolean | null;
  oper_up: boolean | null;
  speed_bps: number | null;
  mtu: number | null;
  in_octets: number | null;
  out_octets: number | null;
  last_seen_at: string;
};

export type DevicePort = {
  id: number;
  device_id: number;
  port: number;
  protocol: string;
  service_name: string | null;
  service_version: string | null;
  banner: string | null;
  last_seen_at: string;
};

export type VulnSeverity = "info" | "low" | "medium" | "high" | "critical";

export type NetworkEventKind =
  | "new_device"
  | "new_open_port"
  | "port_scan"
  | "arp_spoof"
  | "outbound_suspicious"
  | "ids_alert";

export type NetworkEventItem = {
  id: number;
  machine_id: number;
  device_id: number | null;
  kind: NetworkEventKind;
  severity: VulnSeverity;
  message: string;
  src_ip: string | null;
  dst_ip: string | null;
  dst_port: number | null;
  status: string;
  created_at: string;
};

export type Vuln = {
  id: number;
  device_id: number;
  port_id: number | null;
  cve_id: string | null;
  title: string;
  severity: VulnSeverity;
  cvss: number | null;
  description: string | null;
  source: string;
  detected_at: string;
  device_ip: string | null;
  device_hostname: string | null;
};

export type NetworkState =
  | "indisponible"
  | "sain"
  | "surveille"
  | "alarme"
  | "sature"
  | "critique";

export type NetworkStateReason = {
  state: NetworkState;
  label: string;
  count: number;
};

export type NetworkSummary = {
  state: NetworkState;
  reasons: NetworkStateReason[];
  total: number;
  up: number;
  down: number;
  gateways: number;
  new_last_window: number;
  by_type: Record<string, number>;
  last_scan_at: string | null;
  events_recent: number;
};
