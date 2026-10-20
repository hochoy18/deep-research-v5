"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { AuthApiError, login } from "../../lib/api";
import { useAuth } from "../../lib/useAuth";

export default function LoginPage() {
  const router = useRouter();
  const { signIn } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const result = await login({ username, password });
      signIn({ token: result.token, userId: result.user_id });
      router.replace("/dashboard");
    } catch (err) {
      if (err instanceof AuthApiError) {
        setError(err.message || "Login failed");
      } else {
        setError("Network error — please try again");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="card">
      <h1 className="title">Log in</h1>
      <p className="subtitle">Welcome back. Enter your credentials.</p>

      {error && <div className="error">{error}</div>}

      <form onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="username">Username</label>
          <input
            id="username"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            maxLength={255}
          />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            maxLength={72}
          />
        </div>
        <button className="btn" type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p className="alt">
        New here? <a href="/signup">Create an account</a>
      </p>
    </div>
  );
}