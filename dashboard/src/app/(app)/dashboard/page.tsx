"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface EvalRun {
  id: string;
  git_sha: string;
  created_at: string;
  config: Record<string, unknown>;
  scores: Record<string, number>;
}

interface QueryRow {
  id: string;
  question: string;
  answer: string;
  confidence: number;
  abstained: boolean;
  latency_ms: number;
  created_at: string;
}

interface ClaimStats {
  verified: number;
  unsupported: number;
  contradicted: number;
}

const METRICS = [
  { key: "retrieval_hit_rate", label: "Retrieval hit", color: "#7c6cff" },
  { key: "answer_success_rate", label: "Answer success", color: "#34d399" },
  { key: "abstention_accuracy", label: "Abstention acc.", color: "#22d3ee" },
];

export default function DashboardPage() {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [queries, setQueries] = useState<QueryRow[]>([]);
  const [claimStats, setClaimStats] = useState<ClaimStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api<EvalRun[]>("/evals/runs"),
      api<QueryRow[]>("/queries?limit=25"),
      api<ClaimStats>("/queries/claim-stats"),
    ])
      .then(([r, q, c]) => {
        setRuns(r);
        setQueries(q);
        setClaimStats(c);
      })
      .catch((e) => setError(e.message));
  }, []);

  const meanConf = queries.length
    ? queries.reduce((s, q) => s + q.confidence, 0) / queries.length
    : 0;
  const abstainRate = queries.length
    ? queries.filter((q) => q.abstained).length / queries.length
    : 0;
  const totalClaims = claimStats
    ? claimStats.verified + claimStats.unsupported + claimStats.contradicted
    : 0;

  return (
    <div className="max-w-5xl mx-auto p-8 space-y-6">
      <div>
        <h1 className="text-lg font-semibold mb-1">Dashboard</h1>
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          Quality and trust metrics, straight from the platform&apos;s own data.
        </p>
      </div>

      {error && (
        <div className="text-sm rounded-lg px-3 py-2" style={{ color: "var(--amber)", background: "rgba(251,191,36,0.08)" }}>
          {error}
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Queries" value={String(queries.length)} sub="recent" />
        <StatCard label="Mean confidence" value={meanConf.toFixed(2)} sub={meanConf >= 0.7 ? "healthy" : "watch"} good={meanConf >= 0.7} />
        <StatCard label="Abstain rate" value={`${(abstainRate * 100).toFixed(0)}%`} sub="honest refusals" />
        <StatCard
          label="Claims verified"
          value={claimStats ? `${claimStats.verified}/${totalClaims}` : "—"}
          sub={claimStats && totalClaims ? `${((claimStats.verified / totalClaims) * 100).toFixed(0)}% of all claims` : "no claims yet"}
          good={claimStats ? claimStats.verified >= claimStats.unsupported : false}
        />
      </div>

      {/* Eval history chart */}
      <section className="rounded-2xl border p-6" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-sm font-medium">Eval score history</h2>
          <span className="text-xs" style={{ color: "var(--muted)" }}>
            per git SHA · <code className="font-mono">make eval</code> to add a point
          </span>
        </div>
        {runs.length === 0 ? (
          <p className="text-xs py-10 text-center" style={{ color: "var(--muted)" }}>
            No eval runs yet — run <code className="font-mono">make eval</code> in the repo.
          </p>
        ) : (
          <EvalChart runs={[...runs].reverse()} />
        )}
      </section>

      {/* Claim distribution */}
      {claimStats && totalClaims > 0 && (
        <section className="rounded-2xl border p-6" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
          <h2 className="text-sm font-medium mb-4">Claim verdicts</h2>
          <div className="flex h-3 rounded-full overflow-hidden">
            <Bar value={claimStats.verified} total={totalClaims} color="#34d399" />
            <Bar value={claimStats.unsupported} total={totalClaims} color="#fbbf24" />
            <Bar value={claimStats.contradicted} total={totalClaims} color="#f87171" />
          </div>
          <div className="flex gap-5 mt-3 text-xs" style={{ color: "var(--muted)" }}>
            <span><Dot color="#34d399" /> verified ({claimStats.verified})</span>
            <span><Dot color="#fbbf24" /> unsupported ({claimStats.unsupported})</span>
            <span><Dot color="#f87171" /> contradicted ({claimStats.contradicted})</span>
          </div>
        </section>
      )}

      {/* Query log */}
      <section className="rounded-2xl border overflow-hidden" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
        <div className="px-6 py-4 border-b" style={{ borderColor: "var(--border)" }}>
          <h2 className="text-sm font-medium">Recent queries</h2>
        </div>
        {queries.length === 0 ? (
          <p className="text-xs p-8 text-center" style={{ color: "var(--muted)" }}>No queries yet — ask something in Chat.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs" style={{ color: "var(--muted)" }}>
                <th className="px-6 py-2.5 font-normal">Question</th>
                <th className="px-3 py-2.5 font-normal">Confidence</th>
                <th className="px-3 py-2.5 font-normal">Latency</th>
                <th className="px-6 py-2.5 font-normal font-mono">When</th>
              </tr>
            </thead>
            <tbody>
              {queries.map((q) => (
                <tr key={q.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="px-6 py-3 max-w-md">
                    <div className="truncate">{q.question}</div>
                    {q.abstained && (
                      <span className="text-[10px] uppercase tracking-wide" style={{ color: "var(--amber)" }}>abstained</span>
                    )}
                  </td>
                  <td className="px-3 py-3 font-mono text-xs" style={{ color: q.confidence >= 0.7 ? "var(--green)" : q.confidence >= 0.5 ? "var(--amber)" : "#f87171" }}>
                    {q.confidence.toFixed(2)}
                  </td>
                  <td className="px-3 py-3 font-mono text-xs" style={{ color: "var(--muted)" }}>{q.latency_ms}ms</td>
                  <td className="px-6 py-3 text-xs" style={{ color: "var(--muted)" }}>
                    {new Date(q.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function StatCard({ label, value, sub, good }: { label: string; value: string; sub?: string; good?: boolean }) {
  return (
    <div className="rounded-2xl border p-5" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
      <div className="text-xs mb-2" style={{ color: "var(--muted)" }}>{label}</div>
      <div className="text-2xl font-semibold" style={good === undefined ? {} : { color: good ? "var(--green)" : "var(--amber)" }}>
        {value}
      </div>
      {sub && <div className="text-[11px] mt-1" style={{ color: "var(--muted)" }}>{sub}</div>}
    </div>
  );
}

function EvalChart({ runs }: { runs: EvalRun[] }) {
  const W = 720, H = 180, PAD = 28;
  const x = (i: number) => PAD + (i * (W - 2 * PAD)) / Math.max(runs.length - 1, 1);
  const y = (v: number) => H - PAD - v * (H - 2 * PAD);

  return (
    <div className="overflow-x-auto">
      <svg width={W} height={H + 24} className="mt-2">
        {[0, 0.5, 1].map((g) => (
          <g key={g}>
            <line x1={PAD} x2={W - PAD} y1={y(g)} y2={y(g)} stroke="var(--border)" strokeDasharray="3 4" />
            <text x={PAD - 6} y={y(g) + 4} textAnchor="end" fontSize="9" fill="var(--muted)" fontFamily="var(--font-mono)">{g}</text>
          </g>
        ))}
        {METRICS.map((m) => {
          const pts = runs.map((r, i) => `${x(i)},${y(Math.min(r.scores[m.key] ?? 0, 1))}`).join(" ");
          return (
            <g key={m.key}>
              <polyline points={pts} fill="none" stroke={m.color} strokeWidth="2" strokeLinejoin="round" />
              {runs.map((r, i) => (
                <circle key={r.id} cx={x(i)} cy={y(Math.min(r.scores[m.key] ?? 0, 1))} r="3" fill={m.color} />
              ))}
            </g>
          );
        })}
        {runs.map((r, i) => (
          <text key={r.id} x={x(i)} y={H + 14} textAnchor="middle" fontSize="9" fill="var(--muted)" fontFamily="var(--font-mono)">
            {r.git_sha.slice(0, 7)}
          </text>
        ))}
      </svg>
      <div className="flex gap-4 text-xs mt-1" style={{ color: "var(--muted)" }}>
        {METRICS.map((m) => <span key={m.key}><Dot color={m.color} /> {m.label}</span>)}
      </div>
    </div>
  );
}

function Bar({ value, total, color }: { value: number; total: number; color: string }) {
  if (!value) return null;
  return <div style={{ width: `${(value / total) * 100}%`, background: color }} />;
}

function Dot({ color }: { color: string }) {
  return <span className="inline-block w-2 h-2 rounded-full mr-1.5 align-middle" style={{ background: color }} />;
}
