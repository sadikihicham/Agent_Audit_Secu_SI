"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login } from "@/lib/api";
import { setToken } from "@/lib/auth";
import { Logo } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";

const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? "0.1.0";

export default function LoginPage() {
  const router = useRouter();
  // Identifiants de démo pré-remplis (uniquement si fournis via l'env, ex. en dev).
  const [email, setEmail] = useState(process.env.NEXT_PUBLIC_DEMO_EMAIL ?? "");
  const [password, setPassword] = useState(process.env.NEXT_PUBLIC_DEMO_PASSWORD ?? "");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const token = await login(email, password);
      setToken(token);
      router.replace("/dashboard");
    } catch {
      setError("Email ou mot de passe incorrect");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center px-4">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>

      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <Logo className="h-12" />
          <div className="space-y-1">
            <h1 className="bg-gradient-to-r from-sky-500 to-emerald-500 bg-clip-text text-2xl font-bold text-transparent dark:from-sky-400 dark:to-emerald-400">
              GuardianOps AI
            </h1>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Connexion au dashboard
            </p>
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-xs dark:border-slate-700/50 dark:bg-slate-800/40 dark:shadow-none"
        >
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              placeholder="admin@guardianops.ai"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-sky-500 focus:outline-hidden focus:ring-1 focus:ring-sky-500 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-100 dark:placeholder-slate-600"
            />
          </div>

          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">
              Mot de passe
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:outline-hidden focus:ring-1 focus:ring-sky-500 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-100"
            />
          </div>

          {error && <p className="text-xs text-rose-500 dark:text-rose-400">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-sky-600 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50"
          >
            {loading ? "Connexion…" : "Se connecter"}
          </button>
        </form>

        <footer className="space-y-0.5 text-center text-xs text-slate-400 dark:text-slate-600">
          <p>
            Développé par{" "}
            <span className="font-semibold text-slate-500 dark:text-slate-400">
              Infinity
            </span>
          </p>
          <p>Version {APP_VERSION}</p>
        </footer>
      </div>
    </main>
  );
}
