"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const NAV = [
  { href: "/", label: "Batch", hint: "The run and its result" },
  { href: "/records", label: "Records", hint: "All 100 decisions" },
  { href: "/ledger", label: "Audit trail", hint: "Hash-chained rows" },
  { href: "/method", label: "Method", hint: "What is real, what is not" },
];

function Glyph({ name, active }: { name: string; active: boolean }) {
  const c = active ? "#f2efe7" : "#8b857a";
  const common = { stroke: c, strokeWidth: 1.6, fill: "none" as const };
  switch (name) {
    case "Batch":
      // Three attempt slots — the budget this whole product is about.
      return (
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
          <rect x="1.5" y="5" width="4" height="8" rx="1.4" fill={c} />
          <rect x="7" y="5" width="4" height="8" rx="1.4" {...common} />
          <rect x="12.5" y="5" width="4" height="8" rx="1.4" {...common} />
        </svg>
      );
    case "Records":
      return (
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
          <path d="M3 4h12M3 9h12M3 14h7" {...common} strokeLinecap="round" />
        </svg>
      );
    case "Audit trail":
      // Chain links — the ledger is hash-chained.
      return (
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
          <rect x="2" y="6.5" width="6.5" height="5" rx="2.5" {...common} />
          <rect x="9.5" y="6.5" width="6.5" height="5" rx="2.5" {...common} />
        </svg>
      );
    default:
      return (
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
          <circle cx="9" cy="9" r="6.5" {...common} />
          <path d="M9 6v3.5l2.5 1.5" {...common} strokeLinecap="round" />
        </svg>
      );
  }
}

export default function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <>
      {/* Mobile bar */}
      <div className="sticky top-0 z-40 flex items-center justify-between border-b border-rule bg-ink px-4 py-3 lg:hidden">
        <Link href="/" className="flex items-center gap-2.5">
          <Mark />
          <span className="display text-[17px] font-semibold text-paper">Vasooli</span>
        </Link>
        <button
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label={open ? "Close menu" : "Open menu"}
          className="rounded-md p-1.5 text-paper/70 hover:bg-white/10 hover:text-paper"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
            <path
              d={open ? "M5 5l10 10M15 5L5 15" : "M3.5 6h13M3.5 10h13M3.5 14h13"}
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>

      {open && (
        <nav className="border-b border-white/10 bg-ink px-3 pb-4 lg:hidden">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              onClick={() => setOpen(false)}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-[15px] ${
                pathname === n.href ? "bg-white/10 text-paper" : "text-paper/60"
              }`}
            >
              <Glyph name={n.label} active={pathname === n.href} />
              {n.label}
            </Link>
          ))}
        </nav>
      )}

      {/* Desktop rail */}
      <aside className="sticky top-0 hidden h-screen w-[236px] shrink-0 flex-col bg-ink px-5 py-7 lg:flex">
        <Link href="/" className="mb-9 flex items-center gap-2.5 px-2">
          <Mark />
          <span className="display text-[19px] font-semibold text-paper">Vasooli</span>
        </Link>

        <nav className="flex flex-col gap-0.5">
          {NAV.map((n) => {
            const active = pathname === n.href;
            return (
              <Link
                key={n.href}
                href={n.href}
                className={`group relative flex items-start gap-3 rounded-lg px-3 py-2.5 transition-colors ${
                  active ? "bg-white/[0.08]" : "hover:bg-white/[0.04]"
                }`}
              >
                {active && (
                  <span className="absolute top-1/2 -left-5 h-7 w-[3px] -translate-y-1/2 rounded-r bg-mustard" />
                )}
                <span className="mt-px shrink-0">
                  <Glyph name={n.label} active={active} />
                </span>
                <span className="min-w-0">
                  <span
                    className={`block text-[14px] leading-tight ${
                      active ? "font-medium text-paper" : "text-paper/65"
                    }`}
                  >
                    {n.label}
                  </span>
                  <span className="mt-0.5 block text-[11px] leading-tight text-paper/35">
                    {n.hint}
                  </span>
                </span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto space-y-3 px-2">
          <div className="rounded-lg border border-white/10 px-3 py-2.5">
            <p className="font-mono text-[10px] tracking-widest text-paper/40 uppercase">
              Data
            </p>
            <p className="mt-1 text-[12px] leading-snug text-paper/60">
              Synthetic batch, seed 42. Outcomes are modelled, not measured.
            </p>
          </div>
          <a
            href="https://github.com/akshat333-debug/Vasooli"
            className="block text-[12px] text-paper/40 transition-colors hover:text-paper/70"
          >
            github.com/akshat333-debug/Vasooli ↗
          </a>
        </div>
      </aside>
    </>
  );
}

function Mark() {
  // Three slots, one spent. The product in one glyph.
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden>
      <rect x="1" y="1" width="20" height="20" rx="6" fill="#f2efe7" />
      <rect x="5" y="6.5" width="3.2" height="9" rx="1.2" fill="#1c1b19" />
      <rect x="9.4" y="6.5" width="3.2" height="9" rx="1.2" fill="#1c1b19" opacity="0.28" />
      <rect x="13.8" y="6.5" width="3.2" height="9" rx="1.2" fill="#1c1b19" opacity="0.28" />
    </svg>
  );
}
