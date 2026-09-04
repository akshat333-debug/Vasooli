"use client";

import { useState } from "react";
import { rupees, type BatchRecord } from "@/lib/data";

/**
 * The exception list — every record the sequencer did not recover, grouped by
 * why. No filter, no top-N, no "notable cases". A recovery report that shows
 * the wins and hides the rest is marketing, so this component has no mechanism
 * for hiding anything: the groups collapse, but nothing is ever omitted.
 */

// Grouping key is the structured (rule, escalation) pair the engine exports,
// not a slice of the verdict string. The old string split ran on an em dash,
// and rules 5 and 6 interpolate the rupee amount BEFORE that dash -- so every
// above-cap record formed a group of one and the list read as noise.
function groupKey(r: BatchRecord) {
  return `${r.sequencer.rule_fired ?? r.rule_fired}|${r.sequencer.escalation ?? "NONE"}`;
}

// The headline of a group is one member's verdict, trimmed. It is a label for
// a group the engine defined, not the definition of the group.
function groupHeadline(reason: string) {
  return reason.split(" \u2014 ")[0].split(" - ")[0];
}

export default function ExceptionList({
  records,
  escalationLabels,
}: {
  records: BatchRecord[];
  escalationLabels: Record<string, string>;
}) {
  const [open, setOpen] = useState<string | null>(null);

  const unrecovered = records.filter((r) => !r.sequencer.recovered);
  const groups = new Map<string, BatchRecord[]>();
  for (const r of unrecovered) {
    const k = groupKey(r);
    groups.set(k, [...(groups.get(k) ?? []), r]);
  }
  const sorted = [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  const stillAtRisk = unrecovered.reduce((a, r) => a + r.amount_paise, 0);

  return (
    <section className="overflow-hidden rounded-2xl border border-rule bg-paper-raised">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-rule px-6 py-5 sm:px-8">
        <div>
          <p className="eyebrow mb-2">Exception list</p>
          <h2 className="display text-[20px] font-semibold sm:text-[23px]">
            {unrecovered.length} of {records.length} records were not recovered.
          </h2>
          <p className="mt-1.5 text-[13.5px] text-ink-mute">
            {rupees(stillAtRisk)} still at risk. Every one is listed. Nothing is
            filtered out of this view.
          </p>
        </div>
      </div>

      <ul>
        {sorted.map(([key, items]) => {
          const value = items.reduce((a, r) => a + r.amount_paise, 0);
          const isOpen = open === key;
          const headline = groupHeadline(items[0].sequencer.terminal_reason);
          const escalation = items[0].sequencer.escalation ?? "NONE";
          return (
            <li key={key} className="border-b border-rule/70 last:border-0">
              <button
                onClick={() => setOpen(isOpen ? null : key)}
                aria-expanded={isOpen}
                className="flex w-full items-center gap-4 px-6 py-3.5 text-left transition-colors hover:bg-paper-sunk/45 sm:px-8"
              >
                <span className="tnum w-8 shrink-0 text-[15px] font-semibold">
                  {items.length}
                </span>
                <span className="tnum w-28 shrink-0 text-[13px] text-ink-mute">
                  {rupees(value)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="verdict block truncate">{headline}</span>
                  <span className="mt-0.5 block truncate text-[11.5px] text-ink-mute">
                    {escalationLabels[escalation] ?? "no route assigned"}
                  </span>
                </span>
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 14 14"
                  className={`shrink-0 text-ink-faint transition-transform duration-200 ${
                    isOpen ? "rotate-90" : ""
                  }`}
                  aria-hidden
                >
                  <path
                    d="M5 3l4 4-4 4"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    fill="none"
                    strokeLinecap="round"
                  />
                </svg>
              </button>

              {isOpen && (
                <div className="scroll-slim max-h-64 overflow-y-auto border-t border-rule/60 bg-paper-sunk/35 px-6 py-3 sm:px-8">
                  {items.map((r) => (
                    <div
                      key={r.subscription_id}
                      className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-1.5"
                    >
                      <span className="font-mono text-[12px] text-ink">
                        {r.subscription_id}
                      </span>
                      <span className="tnum text-[12px] text-ink-mute">
                        {rupees(r.amount_paise, { decimals: true })}
                      </span>
                      <span className="text-[12px] text-ink-faint">{r.bank}</span>
                      <span className="font-mono text-[11.5px] text-ink-faint">
                        {r.failure_class.toLowerCase().replace(/_/g, " ")}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
