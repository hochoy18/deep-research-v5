/**
 * Thin wrapper around `fetch` for the v5 backend.
 *
 * - All paths are relative to `NEXT_PUBLIC_API_BASE`.
 * - `bearerAuthHeader()` is the only place the token is added to a
 *   request. The bearer store stays in one place; this module never
 *   imports it directly except through that helper.
 */

import { readBearer } from "./bearer";

export type ApiError = {
  status: number;
  message: string;
};

export class AuthApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function signup(input: {
  username: string;
  password: string;
}): Promise<{ token: string; user_id: string }> {
  const res = await fetch(`${API_BASE}/auth/signup`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  await ensureOk(res);
  return (await res.json()) as { token: string; user_id: string };
}

export async function login(input: {
  username: string;
  password: string;
}): Promise<{ token: string; user_id: string }> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  await ensureOk(res);
  return (await res.json()) as { token: string; user_id: string };
}

export async function logout(): Promise<void> {
  const bearer = readBearer();
  if (!bearer) return;
  const res = await fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    headers: { authorization: `Bearer ${bearer.token}` },
  });
  // Even on 401 (already revoked) the local side should still drop the
  // token — so we don't surface logout failures as exceptions here.
  if (!res.ok && res.status !== 401) {
    const detail = await readError(res);
    throw new AuthApiError(res.status, detail);
  }
}

export async function me(): Promise<{
  user_id: string;
  username: string;
  created_at: string;
}> {
  const bearer = readBearer();
  if (!bearer) throw new AuthApiError(401, "no bearer");
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: { authorization: `Bearer ${bearer.token}` },
  });
  await ensureOk(res);
  return (await res.json()) as {
    user_id: string;
    username: string;
    created_at: string;
  };
}

async function ensureOk(res: Response): Promise<void> {
  if (res.ok) return;
  const detail = await readError(res);
  throw new AuthApiError(res.status, detail);
}

async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: string };
    return body.detail ?? res.statusText;
  } catch {
    return res.statusText;
  }
}