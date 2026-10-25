"use client";

/**
 * Time-travel date picker: a compact trigger chip that opens a dark-themed
 * calendar popover. Replaces the native <input type="date">, whose picker
 * renders inconsistently (Safari opens it below the field and clips it).
 */

import { useEffect, useRef, useState } from "react";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function toISO(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear()
    && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate();
}

export default function DatePickerPopover({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange: (iso: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState(() => new Date());
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const selected = value ? new Date(`${value}T00:00:00`) : null;
  const today = new Date();

  const grid: (Date | null)[] = [];
  const first = new Date(view.getFullYear(), view.getMonth(), 1);
  const daysInMonth = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
  for (let i = 0; i < first.getDay(); i++) grid.push(null);
  for (let d = 1; d <= daysInMonth; d++) {
    grid.push(new Date(view.getFullYear(), view.getMonth(), d));
  }

  const pick = (d: Date) => {
    onChange(toISO(d));
    setOpen(false);
  };

  const label = selected
    ? selected.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
    : "As of date";

  return (
    <div ref={rootRef} className="relative shrink-0">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        title="Time travel — answer as of this date"
        className="flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-xs transition-colors disabled:opacity-40"
        style={{
          border: `1px solid ${value ? "var(--cyan)" : "var(--border)"}`,
          color: value ? "var(--cyan)" : "var(--muted)",
          background: "var(--panel-2)",
        }}
      >
        <span aria-hidden>📅</span>
        <span className="whitespace-nowrap">{label}</span>
      </button>

      {open && (
        <div
          className="absolute bottom-full right-0 mb-2 z-50 rounded-2xl p-3 shadow-2xl"
          style={{ border: "1px solid var(--border)", background: "var(--panel)" }}
        >
          {/* Month header */}
          <div className="flex items-center justify-between mb-2 w-60">
            <button
              type="button"
              className="rounded-lg px-2 py-0.5 text-xs"
              style={{ color: "var(--muted)" }}
              onClick={() => setView(new Date(view.getFullYear(), view.getMonth() - 1, 1))}
              aria-label="Previous month"
            >
              ‹
            </button>
            <span className="text-xs font-medium">
              {MONTHS[view.getMonth()]} {view.getFullYear()}
            </span>
            <button
              type="button"
              className="rounded-lg px-2 py-0.5 text-xs"
              style={{ color: "var(--muted)" }}
              onClick={() => setView(new Date(view.getFullYear(), view.getMonth() + 1, 1))}
              aria-label="Next month"
            >
              ›
            </button>
          </div>

          {/* Weekday header */}
          <div className="grid grid-cols-7 mb-1">
            {WEEKDAYS.map((w) => (
              <div key={w} className="text-center text-[10px] w-8" style={{ color: "var(--muted)" }}>
                {w}
              </div>
            ))}
          </div>

          {/* Day grid */}
          <div className="grid grid-cols-7">
            {grid.map((d, i) =>
              d === null ? (
                <div key={`e${i}`} className="w-8 h-8" />
              ) : (
                <button
                  key={d.toISOString()}
                  type="button"
                  onClick={() => pick(d)}
                  className="w-8 h-8 rounded-lg text-xs transition-colors"
                  style={
                    selected && sameDay(d, selected)
                      ? { background: "var(--cyan)", color: "#04121a", fontWeight: 600 }
                      : sameDay(d, today)
                        ? { border: "1px solid var(--cyan)", color: "var(--cyan)" }
                        : { color: "var(--fg, #e5e7eb)" }
                  }
                >
                  {d.getDate()}
                </button>
              )
            )}
          </div>

          {/* Footer: quick clear / today */}
          <div className="flex items-center justify-between mt-2 pt-2" style={{ borderTop: "1px solid var(--border)" }}>
            <button
              type="button"
              className="text-[11px]"
              style={{ color: "var(--muted)" }}
              onClick={() => { onChange(""); setOpen(false); }}
            >
              Clear
            </button>
            <button
              type="button"
              className="text-[11px]"
              style={{ color: "var(--cyan)" }}
              onClick={() => pick(new Date())}
            >
              Today
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
