"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "../../lib/useAuth";

/**
 * Placeholder dashboard. Issue #2 only ships auth; the real session /
 * report UI arrives in later tickets. This page exists so the post-login
 * redirect has somewhere to land and so the user can sign out cleanly.
 */
export default function DashboardPage() {
  const router = useRouter();
  const { bearer, whoami, ready, signOut } = useAuth();

  useEffect(() => {
    if (ready && !bearer) {
      router.replace("/login");
    }
  }, [ready, bearer, router]);

  if (!ready) {
    return <p>Loading…</p>;
  }

  return (
    <div className="card" style={{ maxWidth: 520 }}>
      <h1 className="title">Welcome{whoami ? `, ${whoami.username}` : ""}</h1>
      <p className="subtitle">
        Auth ticket (issue #2) is shipped. Sessions, plans, and reports
        arrive in the next tickets.
      </p>
      <button
        className="btn"
        onClick={async () => {
          await signOut();
          router.replace("/login");
        }}
      >
        Sign out
      </button>
    </div>
  );
}