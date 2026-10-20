"use client";

import { useCallback, useEffect, useState } from "react";

import { AuthApiError, logout as apiLogout, me } from "./api";
import { clearBearer, readBearer, writeBearer, type StoredBearer } from "./bearer";

/**
 * The single auth hook used by client components.
 *
 * - `bearer` reflects the stored token (null if absent).
 * - `whoami` is the user as resolved by `/auth/me`; null when not signed in.
 * - `signIn(...)` writes the bearer; the `whoami` lookup happens lazily
 *   on the next page so the form submit returns fast.
 * - `signOut()` calls `/auth/logout`, clears local storage, and drops state.
 */
export function useAuth() {
  const [bearer, setBearer] = useState<StoredBearer | null>(null);
  const [whoami, setWhoami] = useState<{ username: string } | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const existing = readBearer();
    setBearer(existing);
    if (!existing) {
      setReady(true);
      return;
    }
    me()
      .then((u) => setWhoami({ username: u.username }))
      .catch((err) => {
        if (err instanceof AuthApiError && err.status === 401) {
          clearBearer();
          setBearer(null);
        }
      })
      .finally(() => setReady(true));
  }, []);

  const signIn = useCallback((value: StoredBearer) => {
    writeBearer(value);
    setBearer(value);
    setWhoami(null); // resolved on next whoami lookup
  }, []);

  const signOut = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // Local logout should always succeed; remote errors don't block.
    }
    clearBearer();
    setBearer(null);
    setWhoami(null);
  }, []);

  return { bearer, whoami, ready, signIn, signOut };
}