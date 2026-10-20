/**
 * Where the backend lives, and how we prove who we are to it.
 *
 * One module owns both, because both were previously restated per client
 * (`api.ts`, `sessions.ts`, `useSessionEvents.ts` each carried their own
 * copy of the base URL). Four copies of a URL is four chances to ship a
 * frontend that talks to the wrong port.
 *
 * `NEXT_PUBLIC_API_BASE` is read at module load — Next.js inlines it at
 * build time, so a runtime change would not reach the bundle anyway.
 */

import { readBearer } from "./bearer";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/** Absolute URL for a backend path. */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

/**
 * The `authorization` header, or a thrown error when nobody is signed in.
 *
 * Every `/sessions*` call needs this, and each caller throwing its own
 * error only produced three slightly different messages for one mistake.
 */
export function authHeader(): { authorization: string } {
  const bearer = readBearer();
  if (!bearer) {
    throw new Error("no bearer — sign in first");
  }
  return { authorization: `Bearer ${bearer.token}` };
}