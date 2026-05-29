const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8800";

export async function apiFetch<T>(
  path: string,
  token: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(options?.headers as Record<string, string>),
    },
  });

  if (res.status === 401) {
    // Token expired — clear cookie and redirect to login
    if (typeof window !== "undefined") {
      const { clearToken } = await import("./auth");
      clearToken();
      window.location.replace("/login");
    }
    throw new Error("Unauthorized");
  }

  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

/** Obtient un ticket WS à usage unique (TTL 30 s) depuis le serveur. */
export async function fetchWsTicket(token: string): Promise<string> {
  const data = await apiFetch<{ ticket: string }>("/ws/ticket", token, {
    method: "POST",
  });
  return data.ticket;
}

/** Called from the login form — no auth header needed. */
export async function login(email: string, password: string): Promise<string> {
  const body = new URLSearchParams({ username: email, password });
  const res = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });
  if (!res.ok) throw new Error("Email ou mot de passe incorrect");
  const data = await res.json();
  return data.access_token as string;
}
