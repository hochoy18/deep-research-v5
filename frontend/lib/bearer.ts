/**
 * Bearer storage — the single place the auth token lives on the client.
 *
 * The spec calls out "bearer 存一处" so logout and refresh behave
 * consistently. Every read / write routes through this module; nothing
 * else touches `localStorage` directly.
 *
 * Storage choice: `localStorage`. In a later phase a cookie + httpOnly
 * store replaces this so the SPA can use a server action instead. For
 * P1's username + password + JWT surface, localStorage is fine.
 */

const STORAGE_KEY = "v5.bearer";

export type StoredBearer = {
  token: string;
  userId: string;
};

export function readBearer(): StoredBearer | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as StoredBearer;
    if (typeof parsed.token !== "string" || typeof parsed.userId !== "string") {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function writeBearer(value: StoredBearer): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

export function clearBearer(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
}