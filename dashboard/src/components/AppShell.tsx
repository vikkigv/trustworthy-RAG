"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearToken } from "@/lib/api";

const NAV = [
  { href: "/chat", label: "Chat", icon: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" },
  { href: "/documents", label: "Documents", icon: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6" },
  { href: "/dashboard", label: "Dashboard", icon: "M3 3v18h18M7 14l4-4 3 3 5-6" },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <div className="flex min-h-screen">
      {/* Left rail */}
      <aside className="w-60 shrink-0 border-r flex flex-col" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
        <div className="h-14 flex items-center gap-2 px-4 border-b" style={{ borderColor: "var(--border)" }}>
          <div className="w-6 h-6 rounded-md flex items-center justify-center text-[11px] font-bold text-white"
               style={{ background: "linear-gradient(135deg, #7c6cff, #4f46e5)" }}>T</div>
          <span className="font-semibold tracking-tight">TrustRAG</span>
        </div>
        <nav className="flex-1 p-2 space-y-1">
          {NAV.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                  active ? "text-white" : "hover:bg-white/5"
                }`}
                style={active ? { background: "rgba(124,108,255,0.12)", color: "var(--accent)" } : { color: "var(--muted)" }}
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
                  <path d={item.icon} />
                </svg>
                {item.label}
              </Link>
            );
          })}
        </nav>
        <button
          onClick={() => { clearToken(); router.push("/login"); }}
          className="m-2 px-3 py-2 rounded-lg text-sm text-left hover:bg-white/5"
          style={{ color: "var(--muted)" }}
        >
          Sign out
        </button>
      </aside>

      {/* Content */}
      <main className="flex-1 min-w-0">{children}</main>
    </div>
  );
}
