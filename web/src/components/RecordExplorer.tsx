"use client";

import { useMemo, useState } from "react";
import {
  ACTION_LABEL,
  ACTION_TONE,
  TONE_HEX,
  rupees,
  type Action,
  type BatchRecord,
} from "@/lib/data";

const ACTIONS: Action[] = [
  "RETRY_SCHEDULED",
  "STOP_TERMINAL",
  "STOP_EXHAUSTED",
  "HUMAN_REVIEW",
];

/** The ordered rule list from decide.py. Shown so a reader can see not just
 *  which rule fired, but which ones were checked and passed before it. */
const RULES = [
  { n: 1, test: "Retry budget exhausted", action: "STOP_EXHAUSTED" },
  { n: 2, test: "Terminal failure class", action: "STOP_TERMINAL" },
  { n: 3, test: "Mandate not active", action: "STOP_TERMINAL" },
  { n: 4, test: "Failure unclassified", action: "HUMAN_REVIEW" },
  { n: 5, test: "Above the mandate's own cap", action: "HUMAN_REVIEW" },
  { n: 6, test: "Above the RBI standard cap", action: "HUMAN_REVIEW" },
  { n: 7, test: "Mandate expires before notice elapses", action: "STOP_TERMINAL" },
  { n: 8, test: "Eligible — schedule at the best moment", action: "RETRY_SCHEDULED" },
];

function firedRule(r: BatchRecord): number {
  if (r.attempts_remaining <= 0) return 1;
  const terminalClasses = [
    "MANDATE_REVOKED",
    "MANDATE_EXPIRED",
    "MANDATE_PAUSED",
    "LIMIT_EXCEEDED",
  ];
  if (terminalClasses.includes(r.failure_class)) return 2;
  if (r.mandate_status !== "active") return 3;
  if (r.failure_class === "UNKNOWN") return 4;
  if (r.exceeds_mandate_cap) return 5;
  if (r.needs_human_approval) return 6;
  if (r.action === "STOP_TERMINAL") return 7;
  return 8;
}

export default function RecordExplorer({ records }: { records: BatchRecord[] }) {
  const [filter, setFilter] = useState<Action | "ALL">("ALL");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of records) m.set(r.action, (m.get(r.action) ?? 0) + 1);
    return m;
  }, [records]);

  const shown = useMemo(() => {
    const term = q.trim().toLowerCase();
    return records.filter((r) => {
      if (filter !== "ALL" && r.action !== filter) return false;
      if (!term) return true;
      return (
        r.subscription_id.toLowerCase().includes(term) ||
        r.bank.toLowerCase().includes(term) ||
        r.failure_class.toLowerCase().includes(term) ||
        r.error_reason.toLowerCase().includes(term)
      );
    });
  }, [records, filter, q]);

  return (
    <>
      <div className="mb-5 flex flex-wrap items-center gap-2.5">
        <div className="flex flex-wrap gap-1.5">
          <Chip active={filter === "ALL"} onClick={() => setFilter("ALL")}>
            All {records.length}
          </Chip>
          {ACTIONS.map((a) => (
            <Chip key={a} active={filter === a} onClick={() => setFilter(a)} tone={ACTION_TONE[a]}>
              {ACTION_LABEL[a]} {counts.get(a) ?? 0}
            </Chip>
          ))}
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Find a subscription, bank, or failure"
          className="ml-auto w-full rounded-lg border border-rule bg-paper-raised px-3.5 py-2 text-[13.5px] placeholder:text-ink-faint focus:border-ink-faint focus:outline-none sm:w-72"
        />
      </div>

      <div className="overflow-hidden rounded-2xl border border-rule bg-paper-raised">
        <div className="hidden grid-cols-[150px_100px_1fr_140px_92px] gap-4 border-b border-rule px-5 py-2.5 text-[11px] tracking-wider text-ink-faint uppercase md:grid">
          <span>Subscription</span>
          <span className="text-right">Amount</span>
          <span>Failure</span>
          <span>Decision</span>
          <span className="text-right">Budget</span>
        </div>

        {shown.length === 0 ? (
          <p className="px-5 py-12 text-center text-[14px] text-ink-mute">
            No records match that. Clear the search or pick another decision.
          </p>
        ) : (
          <ul>
            {shown.map((r) => (
              <Row
                key={r.subscription_id}
                r={r}
                open={openId === r.subscription_id}
                onToggle={() =>
                  setOpenId(openId === r.subscription_id ? null : r.subscription_id)
                }
              />
            ))}
          </ul>
        )}
      </div>

      <p className="mt-3 text-[12.5px] text-ink-faint">
        Showing {shown.length} of {records.length} records.
      </p>
    </>
  );
}

function Row({
  r,
  open,
  onToggle,
}: {
  r: BatchRecord;
  open: boolean;
  onToggle: () => void;
}) {
  const tone = TONE_HEX[ACTION_TONE[r.action]];
  const fired = firedRule(r);
  const budget = r.attempts_used + r.attempts_remaining;

  return (
    <li className="border-b border-rule/60 last:border-0">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="grid w-full grid-cols-1 gap-1.5 px-5 py-3 text-left transition-colors hover:bg-paper-sunk/45 md:grid-cols-[150px_100px_1fr_140px_92px] md:items-center md:gap-4"
      >
        <span className="font-mono text-[12.5px] text-ink">{r.subscription_id}</span>
        <span className="tnum text-[13px] md:text-right">
          {rupees(r.amount_paise, { decimals: true })}
        </span>
        <span className="truncate text-[13px] text-ink-mute">
          <span className="text-ink-faint">{r.bank}</span>{" "}
          {r.failure_class.toLowerCase().replace(/_/g, " ")}
        </span>
        <span className="flex items-center gap-1.5 text-[12.5px]">
          <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: tone }} />
          {ACTION_LABEL[r.action]}
        </span>
        <span className="flex gap-[3px] md:justify-end">
          {Array.from({ length: budget }).map((_, i) => (
            <span
              key={i}
              className="h-3.5 w-2 rounded-[2px]"
              style={{
                background:
                  i < r.attempts_used
                    ? "transparent"
                    : i < r.attempts_used + r.sequencer.attempts_spent
                      ? "#1c1b19"
                      : "transparent",
                border:
                  i < r.attempts_used
                    ? "1px dashed #c9c3b4"
                    : i < r.attempts_used + r.sequencer.attempts_spent
                      ? "none"
                      : "1px solid #c9c3b4",
              }}
            />
          ))}
        </span>
      </button>

      {open && (
        <div className="border-t border-rule/60 bg-paper-sunk/35 px-5 py-5">
          <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
            <div>
              <p className="eyebrow mb-2">What the bank said</p>
              <p className="verdict mb-4 rounded-lg bg-paper-raised p-3">
                <span className="text-ink-faint">
                  {r.error_code} / {r.error_reason}
                </span>
                <br />
                {r.error_description}
              </p>

              <p className="eyebrow mb-2">How it was classified</p>
              <p className="verdict mb-4">
                {r.failure_class}{" "}
                <span className="text-ink-faint">via {r.diagnosis_source}</span>
                <br />
                <span className="text-ink-faint">{r.diagnosis_rationale}</span>
              </p>

              <p className="eyebrow mb-2">Decision</p>
              <p className="verdict rounded-lg border-l-2 p-3" style={{ borderColor: tone, background: "#faf8f3" }}>
                {r.verdict}
              </p>
            </div>

            <div>
              <p className="eyebrow mb-2.5">Rules checked, in order</p>
              <ol className="space-y-1">
                {RULES.map((rule) => {
                  const isFired = rule.n === fired;
                  const passed = rule.n < fired;
                  return (
                    <li
                      key={rule.n}
                      className={`flex items-start gap-2 rounded px-2 py-1 text-[12px] ${
                        isFired ? "bg-ink text-paper" : ""
                      }`}
                    >
                      <span
                        className={`tnum mt-px w-3.5 shrink-0 font-mono ${
                          isFired ? "text-paper/60" : "text-ink-faint"
                        }`}
                      >
                        {rule.n}
                      </span>
                      <span className={passed ? "text-ink-faint line-through" : ""}>
                        {rule.test}
                      </span>
                    </li>
                  );
                })}
              </ol>
              <p className="mt-2.5 text-[11.5px] leading-relaxed text-ink-faint">
                Struck-through rules were checked and did not apply. The
                highlighted rule is the one that decided this record.
              </p>
            </div>
          </div>
        </div>
      )}
    </li>
  );
}

function Chip({
  children,
  active,
  onClick,
  tone,
}: {
  children: React.ReactNode;
  active: boolean;
  onClick: () => void;
  tone?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12.5px] transition-colors ${
        active
          ? "border-ink bg-ink text-paper"
          : "border-rule bg-paper-raised text-ink-soft hover:border-ink-faint"
      }`}
    >
      {tone && (
        <span
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: TONE_HEX[tone], opacity: active ? 1 : 0.75 }}
        />
      )}
      {children}
    </button>
  );
}
