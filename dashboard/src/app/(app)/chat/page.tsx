"use client";

import { useRef, useState } from "react";
import { Citation, ClaimVerdict, streamQuery } from "@/lib/api";

interface Turn {
  question: string;
  streaming: boolean;
  answerText: string;
  citations: Citation[];
  claims: ClaimVerdict[];
  abstain: boolean;
  reason: string | null;
  confidence: number;
  asOf?: string | null;
  currentCitations: Citation[];
}

export default function ChatPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [asOf, setAsOf] = useState("");
  const [selectedCite, setSelectedCite] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  async function askFull(e: React.FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);

    setTurns((t) => [
      ...t,
      { question, streaming: true, answerText: "", citations: [], claims: [], abstain: false, reason: null, confidence: 0, asOf: asOf || null, currentCitations: [] },
    ]);

    try {
      const events = await streamQuery(question, (tok) =>
        setTurns((t) =>
          t.map((x, i) => (i === t.length - 1 ? { ...x, answerText: x.answerText + tok, citations: x.citations } : x))
        ), asOf || null
      );
      setTurns((t) =>
        t.map((x, i) =>
          i === t.length - 1
            ? {
                ...x,
                citations: events.retrieved,
                currentCitations: events.currentCitations,
                claims: events.claims,
                abstain: events.abstain,
                reason: events.reason,
                confidence: events.confidence,
                streaming: false,
              }
            : x
        )
      );
    } catch {
      setTurns((t) =>
        t.map((x, i) => (i === t.length - 1 ? { ...x, answerText: "⚠ Query failed", streaming: false } : x))
      );
    } finally {
      setBusy(false);
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }

  return (
    <div className="flex h-screen">
      {/* Chat column */}
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="h-14 border-b flex items-center px-6" style={{ borderColor: "var(--border)" }}>
          <h1 className="text-sm font-medium">Chat</h1>
          <span className="ml-3 text-xs rounded-full px-2 py-0.5" style={{ color: "var(--green)", background: "rgba(52,211,153,0.1)" }}>
            every claim verified
          </span>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-8 max-w-3xl w-full mx-auto">
          {turns.length === 0 && (
            <div className="text-center py-24 space-y-3">
              <div className="text-4xl">🛡️</div>
              <p className="text-lg font-medium">Ask your documents anything</p>
              <p className="text-sm" style={{ color: "var(--muted)" }}>
                Answers stream with citations. Every claim is machine-verified.
                <br />If the evidence isn&apos;t there, TrustRAG will tell you.
              </p>
            </div>
          )}

          {turns.map((turn, i) => (
            <div key={i} className="space-y-4">
              {/* Question */}
              <div className="flex justify-end items-center gap-2">
                {turn.asOf && (
                  <span className="text-[10px] font-mono rounded-full px-2 py-1"
                        style={{ color: "var(--cyan)", background: "rgba(34,211,238,0.1)" }}>
                    as of {turn.asOf}
                  </span>
                )}
                <div className="rounded-2xl rounded-br-md px-4 py-2.5 text-sm max-w-[80%] text-white"
                     style={{ background: "linear-gradient(135deg, #7c6cff, #4f46e5)" }}>
                  {turn.question}
                </div>
              </div>

              {/* Answer */}
              <div className="space-y-3">
                {turn.abstain ? (
                  <div className="rounded-xl border px-4 py-3 text-sm"
                       style={{ borderColor: "rgba(251,191,36,0.3)", background: "rgba(251,191,36,0.06)", color: "var(--amber)" }}>
                    <span className="mr-2">🛡️</span>
                    {turn.answerText || "I don't have enough confidence in the retrieved evidence to answer."}
                    {turn.reason && <div className="mt-1.5 text-xs opacity-80">{turn.reason}</div>}
                  </div>
                ) : (
                  <div className={`text-[15px] leading-7 whitespace-pre-wrap ${turn.streaming ? "token" : ""}`}>
                    {renderAnswer(turn, setSelectedCite)}
                  </div>
                )}

                {/* Temporal: policy changed since the as_of date */}
                {!turn.streaming && turn.currentCitations.length > 0 && (
                  <div className="rounded-xl border px-4 py-3 text-sm"
                       style={{ borderColor: "rgba(34,211,238,0.35)", background: "rgba(34,211,238,0.06)" }}>
                    <div className="mb-1.5" style={{ color: "var(--cyan)" }}>⏱ Changed since then</div>
                    {turn.currentCitations.map((c, i) => (
                      <div key={i} className="text-xs leading-5" style={{ color: "var(--muted)" }}>
                        Current version says: “{c.snippet.slice(0, 140)}…”
                      </div>
                    ))}
                  </div>
                )}

                {/* Trust footer */}
                {!turn.streaming && (turn.claims.length > 0 || turn.abstain) && (
                  <div className="flex items-center gap-3 text-xs" style={{ color: "var(--muted)" }}>
                    <ConfidenceBadge value={turn.confidence} />
                    {turn.claims.map((c, j) => (
                      <span key={j} className="inline-flex items-center gap-1 rounded-full px-2 py-0.5"
                            style={{
                              color: c.verdict === "verified" ? "var(--green)" : "var(--amber)",
                              background: c.verdict === "verified" ? "rgba(52,211,153,0.08)" : "rgba(251,191,36,0.08)",
                            }}>
                        {c.verdict === "verified" ? "✓" : "⚠"} claim {j + 1}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <form onSubmit={askFull} className="p-4 max-w-3xl w-full mx-auto">
          <div className="rounded-2xl border flex items-center px-4 py-1 gap-2" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
            <input
              className="flex-1 bg-transparent py-3 text-sm outline-none placeholder:text-[var(--muted)]"
              placeholder={busy ? "Thinking…" : "Ask a question — try something your documents answer"}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={busy}
            />
            <input
              type="date"
              title="Time travel — answer as of this date"
              className="bg-transparent text-xs outline-none cursor-pointer"
              style={{ color: asOf ? "var(--cyan)" : "var(--muted)" }}
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              disabled={busy}
            />
            {asOf && (
              <button type="button" onClick={() => setAsOf("")}
                      className="text-xs" style={{ color: "var(--muted)" }} title="Clear date">✕</button>
            )}
            <button type="submit" disabled={busy || !input.trim()}
                    className="ml-2 rounded-xl px-3.5 py-1.5 text-white text-sm disabled:opacity-40"
                    style={{ background: "linear-gradient(135deg, #7c6cff, #4f46e5)" }}>
              ↑
            </button>
          </div>
        </form>
      </div>

      {/* Citations panel */}
      <aside className="w-96 shrink-0 border-l overflow-y-auto" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
        <div className="h-14 border-b flex items-center px-5 text-sm font-medium" style={{ borderColor: "var(--border)" }}>
          Sources
        </div>
        <div className="p-4 space-y-3">
          {lastCitations(turns).length === 0 && (
            <p className="text-xs" style={{ color: "var(--muted)" }}>
              Retrieved passages appear here — before the answer finishes streaming.
            </p>
          )}
          {lastCitations(turns).map((c) => (
            <button
              key={c.number}
              onClick={() => setSelectedCite(selectedCite === c.number ? null : c.number)}
              className={`w-full text-left rounded-xl border p-3.5 transition-colors hover:border-[var(--accent)] ${selectedCite === c.number ? "border-[var(--accent)]" : ""}`}
              style={{ borderColor: "var(--border)", background: "var(--panel-2)" }}
            >
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-mono text-xs px-1.5 py-0.5 rounded" style={{ color: "var(--accent)", background: "rgba(124,108,255,0.12)" }}>
                  [{c.number}]
                </span>
                <div className="flex gap-1">
                  <LegBadge active={c.dense_rank !== null} label="dense" />
                  <LegBadge active={c.sparse_rank !== null} label="bm25" />
                </div>
              </div>
              <p className="text-xs leading-5 line-clamp-4" style={{ color: "var(--muted)" }}>
                {selectedCite === c.number ? c.snippet : c.snippet.slice(0, 120) + "…"}
              </p>
              <div className="mt-2 font-mono text-[10px]" style={{ color: "var(--muted)" }}>
                rrf {c.rrf_score.toFixed(4)} · chunk #{c.chunk_index}
                {!c.is_current && (
                  <span style={{ color: "var(--cyan)" }}>
                    {" "}· historical ({fmtDate(c.valid_from)} → {fmtDate(c.valid_to)})
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      </aside>
    </div>
  );
}

function renderAnswer(turn: Turn, onSelect: (n: number) => void): React.ReactNode {
  const text = turn.answerText;
  if (!turn.claims.length) {
    return text.split(/(\[\d+\])/g).map((part, i) =>
      /^\[\d+\]$/.test(part) ? (
        <sup key={i} onClick={() => onSelect(parseInt(part.slice(1, -1)))}
            className="cursor-pointer ml-0.5 font-mono text-[11px]" style={{ color: "var(--accent)" }}>
          {part}
        </sup>
      ) : (
        <span key={i}>{part}</span>
      )
    );
  }
  // With verdicts: underline each claim text found in the answer
  let parts: React.ReactNode[] = [text];
  for (const claim of turn.claims) {
    const next: React.ReactNode[] = [];
    for (const part of parts) {
      if (typeof part !== "string") { next.push(part); continue; }
      const idx = part.toLowerCase().indexOf(claim.text.toLowerCase().slice(0, 40));
      if (idx === -1) { next.push(part); continue; }
      const end = idx + Math.min(claim.text.length, 60);
      next.push(part.slice(0, idx));
      next.push(
        <span key={`${claim.text}-${idx}`} title={claim.verdict}
              className={claim.verdict === "verified" ? "claim-verified" : "claim-unsupported"}>
          {part.slice(idx, end)}
        </span>
      );
      next.push(part.slice(end));
    }
    parts = next;
  }
  return parts;
}

function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : "?";
}

function lastCitations(turns: Turn[]): Citation[] {
  for (let i = turns.length - 1; i >= 0; i--) if (turns[i].citations.length) return turns[i].citations;
  return [];
}

function LegBadge({ active, label }: { active: boolean; label: string }) {
  return (
    <span className="font-mono text-[9px] px-1.5 py-0.5 rounded uppercase tracking-wide"
          style={active ? { color: "var(--cyan)", background: "rgba(34,211,238,0.1)" } : { color: "var(--muted)", background: "rgba(255,255,255,0.03)" }}>
      {label}
    </span>
  );
}

function ConfidenceBadge({ value }: { value: number }) {
  const color = value >= 0.7 ? "var(--green)" : value >= 0.5 ? "var(--amber)" : "#f87171";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono"
          style={{ color, background: `color-mix(in srgb, ${color} 10%, transparent)` }}>
      <svg className="w-3 h-3" viewBox="0 0 36 36">
        <circle cx="18" cy="18" r="15" fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="4" />
        <circle cx="18" cy="18" r="15" fill="none" stroke="currentColor" strokeWidth="4"
                strokeDasharray={`${value * 94} 94`} strokeLinecap="round" transform="rotate(-90 18 18)" />
      </svg>
      {value.toFixed(2)}
    </span>
  );
}
