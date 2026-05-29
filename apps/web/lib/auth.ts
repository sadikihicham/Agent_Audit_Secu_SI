"use client";

import Cookies from "js-cookie";

const COOKIE = "guardian_token";

export const getToken = (): string | null =>
  Cookies.get(COOKIE) ?? null;

export const setToken = (token: string): void => {
  Cookies.set(COOKIE, token, { sameSite: "lax" });
};

export const clearToken = (): void => {
  Cookies.remove(COOKIE);
};
