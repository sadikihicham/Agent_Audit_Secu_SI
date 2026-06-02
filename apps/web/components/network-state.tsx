import type {
  DeviceRisk,
  DeviceStatus,
  NetworkState,
  VulnSeverity,
} from "@/lib/types";

// ── État global du réseau ────────────────────────────────────────────────────

type StateMeta = { label: string; badge: string; dot: string };

export const NETWORK_STATE_META: Record<NetworkState, StateMeta> = {
  sain: {
    label: "Sain",
    badge: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border-emerald-500/30",
    dot: "bg-emerald-500",
  },
  surveille: {
    label: "Surveillé",
    badge: "bg-sky-500/15 text-sky-600 dark:text-sky-300 border-sky-500/30",
    dot: "bg-sky-500",
  },
  alarme: {
    label: "Alarme",
    badge: "bg-amber-500/15 text-amber-600 dark:text-amber-300 border-amber-500/30",
    dot: "bg-amber-500",
  },
  sature: {
    label: "Saturé",
    badge: "bg-orange-500/15 text-orange-600 dark:text-orange-300 border-orange-500/30",
    dot: "bg-orange-500",
  },
  critique: {
    label: "Critique",
    badge: "bg-rose-500/15 text-rose-600 dark:text-rose-300 border-rose-500/30",
    dot: "bg-rose-500",
  },
  indisponible: {
    label: "Indisponible",
    badge: "bg-slate-500/15 text-slate-500 dark:text-slate-400 border-slate-500/30",
    dot: "bg-slate-400",
  },
};

export function NetworkStateBadge({
  state,
  size = "md",
}: {
  state: NetworkState;
  size?: "md" | "lg";
}) {
  const meta = NETWORK_STATE_META[state];
  const sizing =
    size === "lg" ? "gap-2 px-4 py-1.5 text-sm" : "gap-1.5 px-2.5 py-0.5 text-xs";
  return (
    <span
      className={`inline-flex items-center rounded-full border font-medium ${sizing} ${meta.badge}`}
    >
      <span className={`h-2 w-2 rounded-full ${meta.dot}`} />
      {meta.label}
    </span>
  );
}

// ── Statut de connectivité d'un appareil ─────────────────────────────────────

const DEVICE_STATUS_META: Record<DeviceStatus, { label: string; cls: string }> = {
  up: { label: "Actif", cls: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border-emerald-500/30" },
  down: { label: "Hors-ligne", cls: "bg-rose-500/15 text-rose-600 dark:text-rose-300 border-rose-500/30" },
  unknown: { label: "Inconnu", cls: "bg-slate-500/15 text-slate-500 dark:text-slate-400 border-slate-500/30" },
};

export function DeviceStatusBadge({ status }: { status: DeviceStatus }) {
  const meta = DEVICE_STATUS_META[status] ?? DEVICE_STATUS_META.unknown;
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs ${meta.cls}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {meta.label}
    </span>
  );
}

// ── Niveau de risque (Phase B : alimenté par les vulnérabilités) ─────────────

const DEVICE_RISK_META: Record<DeviceRisk, { label: string; cls: string }> = {
  safe: { label: "Sain", cls: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300" },
  vulnerable: { label: "Vulnérable", cls: "bg-amber-500/15 text-amber-600 dark:text-amber-300" },
  critical: { label: "Critique", cls: "bg-rose-500/15 text-rose-600 dark:text-rose-300" },
};

export function DeviceRiskBadge({ risk }: { risk: DeviceRisk }) {
  const meta = DEVICE_RISK_META[risk] ?? DEVICE_RISK_META.safe;
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${meta.cls}`}>
      {meta.label}
    </span>
  );
}

// ── Type d'appareil : icône illustrée ────────────────────────────────────────

// Couleur de fond (teinte) par type, déclinée clair/sombre.
const DEVICE_TYPE_TINT: Record<string, string> = {
  router: "bg-sky-500/15 text-sky-600 dark:text-sky-300",
  server: "bg-violet-500/15 text-violet-600 dark:text-violet-300",
  workstation: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300",
  printer: "bg-amber-500/15 text-amber-600 dark:text-amber-300",
  phone: "bg-pink-500/15 text-pink-600 dark:text-pink-300",
  iot: "bg-teal-500/15 text-teal-600 dark:text-teal-300",
  nas: "bg-indigo-500/15 text-indigo-600 dark:text-indigo-300",
  unknown: "bg-slate-500/15 text-slate-500 dark:text-slate-400",
};

// Tracés SVG (style trait, viewBox 24×24) pour chaque type d'appareil.
function DeviceTypeGlyph({ type }: { type: string }) {
  switch (type) {
    case "router":
      return (
        <>
          <rect width="20" height="8" x="2" y="14" rx="2" />
          <path d="M6.01 18H6" />
          <path d="M10.01 18H10" />
          <path d="M15 10v4" />
          <path d="M17.84 7.17a4 4 0 0 0-5.66 0" />
          <path d="M20.66 4.34a8 8 0 0 0-11.31 0" />
        </>
      );
    case "server":
    case "nas":
      return (
        <>
          <rect width="20" height="8" x="2" y="2" rx="2" ry="2" />
          <rect width="20" height="8" x="2" y="14" rx="2" ry="2" />
          <line x1="6" x2="6.01" y1="6" y2="6" />
          <line x1="6" x2="6.01" y1="18" y2="18" />
        </>
      );
    case "workstation":
      // poste de travail / PC portable
      return (
        <path d="M20 16V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9m16 0H4m16 0 1.28 2.55a1 1 0 0 1-.9 1.45H3.62a1 1 0 0 1-.9-1.45L4 16" />
      );
    case "printer":
      return (
        <>
          <path d="M6 9V2h12v7" />
          <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
          <rect width="12" height="8" x="6" y="14" />
        </>
      );
    case "phone":
      return (
        <>
          <rect width="14" height="20" x="5" y="2" rx="2" ry="2" />
          <path d="M12 18h.01" />
        </>
      );
    case "iot":
      return (
        <>
          <rect width="16" height="16" x="4" y="4" rx="2" />
          <rect width="6" height="6" x="9" y="9" rx="1" />
          <path d="M15 2v2" />
          <path d="M15 20v2" />
          <path d="M2 15h2" />
          <path d="M2 9h2" />
          <path d="M20 15h2" />
          <path d="M20 9h2" />
          <path d="M9 2v2" />
          <path d="M9 20v2" />
        </>
      );
    default:
      // inconnu
      return (
        <>
          <circle cx="12" cy="12" r="10" />
          <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
          <path d="M12 17h.01" />
        </>
      );
  }
}

const ICON_SIZE = { sm: "h-8 w-8", md: "h-10 w-10", lg: "h-14 w-14" } as const;
const GLYPH_SIZE = { sm: "h-4 w-4", md: "h-5 w-5", lg: "h-7 w-7" } as const;

export function DeviceTypeIcon({
  type,
  size = "md",
  title,
}: {
  type: string;
  size?: "sm" | "md" | "lg";
  title?: string;
}) {
  const tint = DEVICE_TYPE_TINT[type] ?? DEVICE_TYPE_TINT.unknown;
  return (
    <span
      title={title ?? deviceTypeLabel(type)}
      className={`inline-flex shrink-0 items-center justify-center rounded-lg ${ICON_SIZE[size]} ${tint}`}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.75}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={GLYPH_SIZE[size]}
        aria-hidden="true"
      >
        <DeviceTypeGlyph type={type} />
      </svg>
    </span>
  );
}

// ── Sévérité d'une vulnérabilité ─────────────────────────────────────────────

const VULN_SEVERITY_META: Record<VulnSeverity, { label: string; cls: string }> = {
  critical: { label: "Critique", cls: "bg-rose-500/15 text-rose-600 dark:text-rose-300 border-rose-500/30" },
  high: { label: "Élevée", cls: "bg-orange-500/15 text-orange-600 dark:text-orange-300 border-orange-500/30" },
  medium: { label: "Moyenne", cls: "bg-amber-500/15 text-amber-600 dark:text-amber-300 border-amber-500/30" },
  low: { label: "Faible", cls: "bg-sky-500/15 text-sky-600 dark:text-sky-300 border-sky-500/30" },
  info: { label: "Info", cls: "bg-slate-500/15 text-slate-500 dark:text-slate-400 border-slate-500/30" },
};

export function VulnSeverityBadge({ severity }: { severity: VulnSeverity }) {
  const meta = VULN_SEVERITY_META[severity] ?? VULN_SEVERITY_META.info;
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${meta.cls}`}
    >
      {meta.label}
    </span>
  );
}

export const VULN_SEVERITY_RANK: Record<VulnSeverity, number> = {
  info: 0,
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
};

export const DEVICE_TYPE_LABELS: Record<string, string> = {
  router: "Routeur",
  server: "Serveur",
  workstation: "Poste",
  printer: "Imprimante",
  phone: "Téléphone",
  iot: "IoT",
  nas: "NAS",
  unknown: "Inconnu",
};

export function deviceTypeLabel(type: string): string {
  return DEVICE_TYPE_LABELS[type] ?? type;
}

// ── Types d'événement d'intrusion ────────────────────────────────────────────

export const EVENT_KIND_LABELS: Record<string, string> = {
  new_device: "Nouvel appareil",
  new_open_port: "Nouveau port ouvert",
  port_scan: "Scan de ports",
  arp_spoof: "ARP spoofing",
  outbound_suspicious: "Flux sortant suspect",
  ids_alert: "Alerte IDS",
};

export function eventKindLabel(kind: string): string {
  return EVENT_KIND_LABELS[kind] ?? kind;
}
