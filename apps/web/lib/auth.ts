"use client";

import Cookies from "js-cookie";

const COOKIE = "guardian_token";

export const getToken = (): string | null =>
  Cookies.get(COOKIE) ?? null;

export const setToken = (token: string): void => {
  // Drapeau `secure` activé dès que la page est servie en HTTPS (prod derrière TLS).
  const secure =
    typeof window !== "undefined" && window.location.protocol === "https:";
  Cookies.set(COOKIE, token, { sameSite: "lax", secure });
};

export const clearToken = (): void => {
  Cookies.remove(COOKIE);
};
