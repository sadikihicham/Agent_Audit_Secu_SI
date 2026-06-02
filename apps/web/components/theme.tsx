"use client";

import { createContext, useContext, useEffect, useState } from "react";

export type Theme = "light" | "dark";

type ThemeCtx = { theme: Theme; isDark: boolean; toggle: () => void };

const ThemeContext = createContext<ThemeCtx | null>(null);

const STORAGE_KEY = "guardian_theme";

function apply(theme: Theme): void {
  const el = document.documentElement;
  el.classList.toggle("dark", theme === "dark");
  el.style.colorScheme = theme;
}

function initialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  // Pas de préférence enregistrée → on suit le système (défaut sombre).
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");

  // Synchronise l'état React avec ce que le script anti-FOUC a déjà appliqué.
  // setState au montage est volontaire ici : le thème réel (localStorage) n'est
  // connu que côté client, et l'init serveur reste "dark" pour éviter un mismatch
  // d'hydratation (une lazy-init le provoquerait). La règle est donc inapplicable.
  useEffect(() => {
    const t = initialTheme();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTheme(t);
    apply(t);
  }, []);

  const toggle = () => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      window.localStorage.setItem(STORAGE_KEY, next);
      apply(next);
      return next;
    });
  };

  return (
    <ThemeContext.Provider value={{ theme, isDark: theme === "dark", toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeCtx {
  return useContext(ThemeContext) ?? { theme: "dark", isDark: true, toggle: () => {} };
}
