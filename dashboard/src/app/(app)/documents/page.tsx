"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { DocumentRow, api } from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  indexed: "var(--green)",
  processing: "var(--cyan)",
  pending: "var(--muted)",
  failed: "#f87171",
};

export default function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setDocs(await api<DocumentRow[]>("/documents"));
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000); // live status updates
    return () => clearInterval(t);
  }, [refresh]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    setError(null);
    for (const file of Array.from(files)) {
      const form = new FormData();
      form.append("file", file);
      try {
        const res = await fetch("http://localhost:8000/documents", {
          method: "POST",
          headers: {
            Authorization: `Bearer ${localStorage.getItem("trustrag_token")}`,
          },
          body: form,
        });
        if (!res.ok) setError((await res.text()) || `upload failed: ${file.name}`);
      } catch (e: any) {
        setError(e.message);
      }
    }
    setUploading(false);
    refresh();
  }

  async function remove(id: string) {
    await api(`/documents/${id}`, { method: "DELETE" });
    refresh();
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      <h1 className="text-lg font-semibold mb-1">Documents</h1>
      <p className="text-sm mb-6" style={{ color: "var(--muted)" }}>
        Uploads are parsed, chunked, embedded, and indexed automatically.
      </p>

      {/* Drop zone */}
      <div
        onClick={() => fileInput.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files); }}
        className="rounded-2xl border-2 border-dashed p-10 text-center cursor-pointer mb-6 transition-colors hover:border-[var(--accent)]"
        style={{ borderColor: "var(--border)" }}
      >
        <input ref={fileInput} type="file" multiple hidden
               accept=".pdf,.docx,.md,.txt"
               onChange={(e) => upload(e.target.files)} />
        <div className="text-2xl mb-2">📄</div>
        <p className="text-sm">{uploading ? "Uploading…" : "Drop files here or click to browse"}</p>
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>PDF, DOCX, Markdown, TXT — up to 25 MB each</p>
      </div>

      {error && (
        <div className="mb-4 text-sm rounded-lg px-3 py-2" style={{ color: "#f87171", background: "rgba(248,113,113,0.08)" }}>
          {error}
        </div>
      )}

      {/* List */}
      <div className="rounded-2xl border divide-y" style={{ borderColor: "var(--border)" }}>
        {docs.length === 0 && (
          <div className="p-8 text-center text-sm" style={{ color: "var(--muted)" }}>No documents yet</div>
        )}
        {docs.map((doc) => (
          <div key={doc.id} className="flex items-center gap-4 px-5 py-3.5">
            <div className="w-9 h-9 rounded-lg flex items-center justify-center text-xs"
                 style={{ background: "var(--panel-2)" }}>
              {doc.filename.split(".").pop()?.toUpperCase().slice(0, 4)}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm truncate">{doc.filename}</div>
              <div className="text-xs" style={{ color: "var(--muted)" }}>
                {new Date(doc.created_at).toLocaleString()}
              </div>
            </div>
            <span className="text-xs font-mono rounded-full px-2.5 py-1"
                  style={{
                    color: STATUS_COLORS[doc.status] ?? "var(--muted)",
                    background: `color-mix(in srgb, ${STATUS_COLORS[doc.status] ?? "var(--muted)"} 10%, transparent)`,
                  }}>
              {doc.status}
              {doc.status === "processing" && " ·"}
              {doc.status === "processing" && <span className="animate-pulse"> indexing…</span>}
            </span>
            <button onClick={() => remove(doc.id)}
                    className="text-xs px-2 py-1 rounded hover:bg-white/5" style={{ color: "var(--muted)" }}>
              Delete
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
