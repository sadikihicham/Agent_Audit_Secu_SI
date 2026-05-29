import { HealthBadge } from "@/components/health-badge";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-8 px-6 text-center">
      <div className="space-y-3">
        <h1 className="bg-gradient-to-r from-sky-400 to-emerald-400 bg-clip-text text-5xl font-bold text-transparent">
          GuardianOps AI
        </h1>
        <p className="text-lg text-slate-400">
          Audit permanent SI · Monitoring temps réel · Sécurité · Auto-remediation
        </p>
      </div>

      <div className="flex flex-col items-center gap-3">
        <span className="text-xs uppercase tracking-widest text-slate-500">
          État de l&apos;API
        </span>
        <HealthBadge />
      </div>

      <footer className="mt-12 text-xs text-slate-600">
        MVP · Phase 0 — Socle &amp; infra
      </footer>
    </main>
  );
}
