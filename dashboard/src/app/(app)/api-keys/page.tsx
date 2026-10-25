"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface ApiKeyRow {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
}

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setKeys(await api<ApiKeyRow[]>("/auth/api-keys"));
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      const res = await api<{ raw_key: string }>("/auth/api-keys", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      setCreated(res.raw_key);
      setCopied(false);
      setName("");
      setError(null);
      refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    try {
      await api(`/auth/api-keys/${id}`, { method: "DELETE" });
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
    setConfirmRevoke(null);
    refresh();
  }

  return (
    <div className="max-w-3xl mx-auto p-8">
      <h1 className="text-lg font-semibold mb-1">API keys</h1>
      <p className="text-sm mb-6" style={{ color: "var(--muted)" }}>
        Programmatic access for the REST API and the MCP server (TRUSTRAG_API_KEY).
        Keys are shown <span style={{ color: "var(--amber)" }}>once</span> at creation — store them somewhere safe.
      </p>

      {error && (
        <div className="mb-4 text-sm rounded-lg px-3 py-2" style={{ color: "#f87171", background: "rgba(248,113,113,0.08)" }}>
          {error}
        </div>
      )}

      {created && (
        <div className="mb-6 rounded-2xl border p-4" style={{ borderColor: "rgba(251,191,36,0.35)", background: "rgba(251,191,36,0.06)" }}>
          <div className="text-sm mb-2" style={{ color: "var(--amber)" }}>
            New key — copy it now, it will not be shown again:
          </div>
          <div className="flex items-center gap-3">
            <code className="flex-1 text-xs font-mono rounded-lg px-3 py-2 truncate"
                  style={{ background: "var(--panel-2)", color: "var(--cyan)" }}>
              {created}
            </code>
            <button
              type="button"
              className="text-xs rounded-lg px-3 py-2 border"
              style={{ borderColor: "var(--border)", color: copied ? "var(--green)" : "var(--muted)" }}
              onClick={async () => {
                try { await navigator.clipboard.writeText(created); setCopied(true); } catch {}
              }}
            >
              {copied ? "✓ Copied" : "Copy"}
            </button>
            <button type="button" className="text-xs px-2" style={{ color: "var(--muted)" }} onClick={() => setCreated(null)}>
              ✕
            </button>
          </div>
        </div>
      )}

      <form onSubmit={create} className="flex gap-2 mb-6">
        <input
          className="flex-1 rounded-xl border bg-transparent px-3 py-2.5 text-sm outline-none focus:border-[var(--accent)]"
          style={{ borderColor: "var(--border)", background: "var(--panel)" }}
          placeholder="Key name — e.g. claude-desktop, ci-evals"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={busy}
        />
        <button
          type="submit"
          className="rounded-xl px-4 py-2 text-white text-sm disabled:opacity-40"
          style={{ background: "linear-gradient(135deg, #7c6cff, #4f46e5)" }}
          disabled={busy || !name.trim()}
        >
          Create key
        </button>
      </form>

      <div className="rounded-2xl border divide-y" style={{ borderColor: "var(--border)" }}>
        {keys.length === 0 && (
          <div className="p-8 text-center text-sm" style={{ color: "var(--muted)" }}>
            No API keys yet — create one above to use the MCP server from Claude Desktop or other agents.
          </div>
        )}
        {keys.map((k) => (
          <div key={k.id} className="flex items-center gap-4 px-5 py-3.5">
            <div className="flex-1 min-w-0">
              <div className="text-sm truncate">{k.name}</div>
              <div className="text-xs font-mono" style={{ color: "var(--muted)" }}>
                {k.key_prefix}… · created {new Date(k.created_at).toLocaleDateString()}
              </div>
            </div>
            {confirmRevoke === k.id ? (
              <span className="flex items-center gap-1 text-xs">
                <button onClick={() => revoke(k.id)} className="px-2 py-1 rounded"
                        style={{ color: "#f87171", background: "rgba(248,113,113,0.1)" }}>
                  Confirm revoke
                </button>
                <button onClick={() => setConfirmRevoke(null)} className="px-2 py-1 rounded hover:bg-white/5"
                        style={{ color: "var(--muted)" }}>
                  Cancel
                </button>
              </span>
            ) : (
              <button onClick={() => setConfirmRevoke(k.id)}
                      className="text-xs px-2 py-1 rounded hover:bg-white/5" style={{ color: "var(--muted)" }}>
                Revoke
              </button>
            )}
          </div>
        ))}
      </div>

      <p className="mt-6 text-xs" style={{ color: "var(--muted)" }}>
        To let an AI agent use your documents, pass a key as TRUSTRAG_API_KEY — see{" "}
        <a href="https://github.com/vikkigv/trustworthy-RAG/blob/main/docs/mcp.md" className="underline" style={{ color: "var(--cyan)" }}>
          docs/mcp.md
        </a>{" "}
        for the Claude Desktop setup.
      </p>
    </div>
  );
}
