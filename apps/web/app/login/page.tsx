"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { brain, setSession } from "@/lib/api";
import { ErrorNote, ThemeToggle } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [merchantName, setMerchantName] = useState("");
  const [reserve, setReserve] = useState("2000000");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res =
        mode === "login"
          ? await brain.login(email, password)
          : await brain.register({
              email,
              password,
              merchant_name: merchantName,
              cash_reserve_minimum_paise: Math.round(Number(reserve || 0) * 100),
            });
      setSession(res.access_token);
      router.replace("/app");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth">
      <div className="auth-card">
        <div className="spread">
          <div className="row tight">
            <span className="brand-mark" aria-hidden="true">
              BB
            </span>
            <div>
              <h1 style={{ fontSize: 17 }}>Business Brain</h1>
              <p className="tiny">Razorpay merchant intelligence</p>
            </div>
          </div>
          <ThemeToggle />
        </div>

        <div className="segmented" style={{ width: "fit-content" }}>
          <button type="button" aria-pressed={mode === "login"} onClick={() => setMode("login")}>
            Sign in
          </button>
          <button type="button" aria-pressed={mode === "register"} onClick={() => setMode("register")}>
            New merchant
          </button>
        </div>

        <p className="subtle">
          Every number on the next screens is computed from the Mongo-backed world model — events in, features and state
          out. Nothing is a preset.
        </p>

        <form onSubmit={onSubmit} className="stack-v">
          {mode === "register" && (
            <label className="field">
              Merchant name
              <input value={merchantName} onChange={(e) => setMerchantName(e.target.value)} required placeholder="Atlas Electronics" />
            </label>
          )}
          <label className="field">
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="merchant@atlas.local" />
          </label>
          <label className="field">
            Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required placeholder="••••••••" />
          </label>
          {mode === "register" && (
            <label className="field">
              Minimum cash reserve (₹)
              <input type="number" min={0} value={reserve} onChange={(e) => setReserve(e.target.value)} />
            </label>
          )}
          <ErrorNote>{error}</ErrorNote>
          <button className="btn" disabled={busy} type="submit">
            {busy ? "Working…" : mode === "login" ? "Sign in" : "Create merchant"}
          </button>
        </form>
      </div>
    </main>
  );
}
