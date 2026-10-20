"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "../lib/useAuth";

/**
 * Root page — routes the user to signup / login / a placeholder dashboard
 * based on whether a bearer is present.
 *
 * The dashboard placeholder is intentional: real session UI lands in later
 * tickets. The redirect here is what proves the auth loop is wired end to
 * end.
 */
export default function HomePage() {
  const router = useRouter();
  const { ready, bearer } = useAuth();

  useEffect(() => {
    if (!ready) return;
    if (bearer) {
      router.replace("/dashboard");
    } else {
      router.replace("/login");
    }
  }, [ready, bearer, router]);

  return <p>Loading…</p>;
}