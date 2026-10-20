"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { AuthApiError, signup } from "../../lib/api";
import { useAuth } from "../../lib/useAuth";

export default function SignupPage() {
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
      const result = await signup({ username, password });
      signIn({ token: result.token, userId: result.user_id });
      router.replace("/dashboard");
    } catch (err) {
      if (err instanceof AuthApiError) {
        setError(err.message || "Signup failed");
      } else {
        setError("Network error — please try again");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="card">
      <h1 className="title">Create your account</h1>
      <p className="subtitle">Pick a username and password to start.</p>

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
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            maxLength={72}
            minLength={1}
          />
        </div>
        <button className="btn" type="submit" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>

      <p className="alt">
        Already have an account? <a href="/login">Sign in</a>
      </p>
    </div>
  );
}