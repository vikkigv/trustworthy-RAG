"use client";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "trustrag_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export async function api<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
    },
  });
  if (res.status === 401 && typeof window !== "undefined") {
    window.location.href = "/login";
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `API error ${res.status}`);
  }
  if (res.status === 204) return undefined as T; // DELETE endpoints return no body
  return res.json() as Promise<T>;
}

// --- API types ---

export interface Citation {
  number: number;
  chunk_id: string;
  document_id: string;
  chunk_index: number;
  snippet: string;
  rrf_score: number;
  dense_rank: number | null;
  sparse_rank: number | null;
  valid_from: string | null;
  valid_to: string | null;
  is_current: boolean;
}

export interface ClaimVerdict {
  text: string;
  verdict: "verified" | "unsupported" | "contradicted";
  supporting_chunk_ids: string[];
}

export interface QueryEvents {
  retrieved: Citation[];
  tokens: string[];
  claims: ClaimVerdict[];
  abstain: boolean;
  reason: string | null;
  confidence: number;
  answer: string;
  query_log_id: string | null;
  currentCitations: Citation[];
  searchedAs: string | null;
}

export interface HistoryTurn {
  question: string;
  answer: string;
}

export async function streamQuery(
  question: string,
  onToken: (t: string) => void,
  asOf?: string | null,
  history?: HistoryTurn[]
): Promise<QueryEvents> {
  const res = await fetch(`${API_URL}/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({
      question,
      ...(asOf ? { as_of: asOf } : {}),
      ...(history?.length ? { history: history.slice(-4) } : {}),
    }),
  });
  if (!res.ok || !res.body) throw new Error(`query failed: ${res.status}`);

  const events: QueryEvents = {
    retrieved: [],
    tokens: [],
    claims: [],
    abstain: false,
    reason: null,
    confidence: 0,
    answer: "",
    query_log_id: null,
    currentCitations: [],
    searchedAs: null,
  };
  let currentEvent = "";

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) currentEvent = line.slice(7);
        else if (line.startsWith("data: ")) {
          const data = JSON.parse(line.slice(6));
          handleEvent(events, currentEvent, data, onToken);
        }
      }
    }
  }
  return events;
}

function handleEvent(
  events: QueryEvents,
  kind: string,
  data: any,
  onToken: (t: string) => void
) {
  switch (kind) {
    case "retrieved":
      events.retrieved = data.citations;
      break;
    case "token":
      events.tokens.push(data.text);
      onToken(data.text);
      break;
    case "claims":
      events.claims = data.claims;
      events.abstain = data.abstain;
      events.reason = data.reason;
      break;
    case "done":
      events.answer = data.answer;
      events.confidence = data.confidence;
      events.query_log_id = data.query_log_id;
      events.currentCitations = data.current_citations ?? [];
      events.searchedAs = data.searched_as ?? null;
      // early-abstain path (no chunks) omits the flag; infer it
      events.abstain = Boolean(data.abstain) || events.retrieved.length === 0;
      break;
  }
}

export interface DocumentRow {
  id: string;
  filename: string;
  status: string;
  supersedes_id: string | null;
  created_at: string;
}
