"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { API_URL, setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [tenantName, setTenantName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        const res = await fetch(`${API_URL}/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tenant_name: tenantName, email, password }),
        });
        if (!res.ok) throw new Error((await res.text()) || "Registration failed");
      }
      const res = await fetch(`${API_URL}/auth/token`, {
        method: "POST",
        body: new URLSearchParams({ username: email, password }),
      });
      if (!res.ok) throw new Error("Invalid email or password");
      const { access_token } = await res.json();
      setToken(access_token);
      router.push("/chat");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const input = "w-full rounded-lg px-3 py-2.5 text-sm outline-none border transition-colors focus:border-[var(--accent)]";
  const inputStyle = { background: "var(--panel-2)", borderColor: "var(--border)" };

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2.5 mb-8 justify-center">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center font-bold text-white"
               style={{ background: "linear-gradient(135deg, #7c6cff, #4f46e5)" }}>T</div>
          <div>
            <div className="font-semibold text-lg tracking-tight">TrustRAG</div>
            <div className="text-xs" style={{ color: "var(--muted)" }}>answers you can verify</div>
          </div>
        </div>

        <form onSubmit={submit} className="rounded-2xl border p-6 space-y-3" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
          <div className="flex rounded-lg p-1 mb-2" style={{ background: "var(--panel-2)" }}>
            {(["login", "register"] as const).map((m) => (
              <button key={m} type="button" onClick={() => setMode(m)}
                      className={`flex-1 py-1.5 rounded-md text-sm capitalize transition-colors ${mode === m ? "bg-[var(--panel)] text-white" : ""}`}
                      style={mode !== m ? { color: "var(--muted)" } : {}}>
                {m === "login" ? "Sign in" : "Create tenant"}
              </button>
            ))}
          </div>

          {mode === "register" && (
            <input className={input} style={inputStyle} placeholder="Tenant / company name"
                   value={tenantName} onChange={(e) => setTenantName(e.target.value)} required minLength={2} />
          )}
          <input className={input} style={inputStyle} type="email" placeholder="Email"
                 value={email} onChange={(e) => setEmail(e.target.value)} required />
          <input className={input} style={inputStyle} type="password" placeholder="Password (min 10 chars)"
                 value={password} onChange={(e) => setPassword(e.target.value)} required minLength={10} />

          {error && <div className="text-sm rounded-lg px-3 py-2" style={{ color: "var(--amber)", background: "rgba(251,191,36,0.08)" }}>{error}</div>}

          <button type="submit" disabled={busy}
                  className="w-full rounded-lg py-2.5 text-sm font-medium text-white transition-opacity disabled:opacity-50"
                  style={{ background: "linear-gradient(135deg, #7c6cff, #4f46e5)" }}>
            {busy ? "…" : mode === "login" ? "Sign in" : "Create tenant & sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
