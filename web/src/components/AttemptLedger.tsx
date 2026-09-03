"use client";

import { useState } from "react";
import type { Arm, BatchRecord } from "@/lib/data";

/**
 * The Attempt Ledger — the signature view.
 *
 * A batch of 100 subscriptions carries a hard budget of 300 retry attempts.
 * Every one of those 300 is drawn here, once, as a cell. Nothing is aggregated
 * away, because the argument this project makes is precisely about how the
 * budget was spent, and an average would hide it.
 *
 * Cell states:
 *   filled dark   an attempt was spent and the debit failed
 *   sage          an attempt was spent and the money came back
 *   hollow        the attempt was preserved — the engine declined to spend it
 *   hatched       the record arrived with its budget already gone
 *
 * Read the two rows against each other and the whole thesis is visible without
 * a single number: the baseline fills its grid, the sequencer leaves most of
 * its budget intact and still recovers more inside the compliance envelope.
 */

type CellState = "recovered" | "burned" | "preserved" | "prespent";

const CELL_FILL: Record<CellState, string> = {
  recovered: "#8fae86",
  burned: "#1c1b19",
  preserved: "transparent",
  prespent: "transparent",
};

function cellsFor(
  records: BatchRecord[],
  arm: Arm,
  budget: number,
): { state: CellState; rec: BatchRecord }[] {
  const byId = new Map(arm.outcomes.map((o) => [o.subscription_id, o]));
  const out: { state: CellState; rec: BatchRecord }[] = [];

  for (const rec of records) {
    const o = byId.get(rec.subscription_id);
    const spent = o?.attempts_spent ?? 0;
    const recovered = o?.recovered ?? false;
    // Attempts already consumed before this batch ever saw the record.
    const prespent = rec.attempts_used;

    for (let i = 0; i < budget; i++) {
      if (i < prespent) out.push({ state: "prespent", rec });
      else if (i < prespent + spent) {
        const isLast = i === prespent + spent - 1;
        out.push({ state: recovered && isLast ? "recovered" : "burned", rec });
      } else out.push({ state: "preserved", rec });
    }
  }
  return out;
}

function Row({
  label,
  sub,
  records,
  arm,
  budget,
  onHover,
}: {
  label: string;
  sub: string;
  records: BatchRecord[];
  arm: Arm;
  budget: number;
  onHover: (r: BatchRecord | null) => void;
}) {
  const cells = cellsFor(records, arm, budget);
  const spent = arm.attempts_spent;
  const pct = Math.round((spent / cells.length) * 100);

  return (
    <div>
      <div className="mb-2.5 flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <h3 className="display text-[15px] font-semibold tracking-tight">{label}</h3>
          <span className="text-[12px] text-ink-mute">{sub}</span>
        </div>
        <div className="tnum shrink-0 text-[12px] text-ink-mute">
          <span className="font-semibold text-ink">{spent}</span>
          <span className="text-ink-faint"> / {cells.length} spent · {pct}%</span>
        </div>
      </div>

      {/* Three hundred coloured squares carry the argument visually and
          nothing at all to a screen reader, so the same facts are stated in
          text. The grid itself is then hidden from the accessibility tree
          rather than read out as 300 anonymous divs. */}
      <p className="sr-only">
        {label}: {spent} of {cells.length} available retry attempts were spent,
        {" "}{cells.filter((c) => c.state === "recovered").length} of which
        recovered the money. {cells.filter((c) => c.state === "preserved").length}
        {" "}attempts were preserved, and{" "}
        {cells.filter((c) => c.state === "prespent").length} had already been
        spent before this batch began.
      </p>

      <div
        aria-hidden="true"
        className="attempt-grid grid gap-[2px]"
        onMouseLeave={() => onHover(null)}
      >
        {cells.map((c, i) => (
          <div
            key={i}
            onMouseEnter={() => onHover(c.rec)}
            title={`${c.rec.subscription_id} · ${c.state}`}
            className="h-[9px] rounded-[1.5px] transition-transform duration-150 hover:scale-[1.6]"
            style={{
              background: CELL_FILL[c.state],
              border:
                c.state === "preserved"
                  ? "1px solid #c9c3b4"
                  : c.state === "prespent"
                    ? "1px dashed #c9c3b4"
                    : "none",
              opacity: c.state === "prespent" ? 0.45 : 1,
            }}
          />
        ))}
      </div>
    </div>
  );
}

export default function AttemptLedger({
  records,
  baseline,
  sequencer,
  budget,
}: {
  records: BatchRecord[];
  baseline: Arm;
  sequencer: Arm;
  budget: number;
}) {
  const [hover, setHover] = useState<BatchRecord | null>(null);
  const total = records.length * budget;

  return (
    <section className="rounded-2xl border border-rule bg-paper-raised p-6 sm:p-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow mb-2">The attempt ledger</p>
          <h2 className="display max-w-xl text-[22px] leading-[1.25] font-semibold sm:text-[26px]">
            Every one of the {total} retries this batch was allowed to spend.
          </h2>
        </div>
        <dl className="flex flex-wrap gap-x-5 gap-y-2 text-[11px]">
          {[
            ["Recovered", "#8fae86", "solid"],
            ["Spent, failed", "#1c1b19", "solid"],
            ["Preserved", "transparent", "solid"],
            ["Already gone", "transparent", "dashed"],
          ].map(([name, fill, style]) => (
            <div key={name as string} className="flex items-center gap-1.5">
              <span
                className="inline-block h-[9px] w-[9px] rounded-[1.5px]"
                style={{
                  background: fill as string,
                  border: fill === "transparent" ? `1px ${style} #c9c3b4` : "none",
                }}
              />
              <span className="text-ink-mute">{name}</span>
            </div>
          ))}
        </dl>
      </div>

      <div className="space-y-7">
        <Row
          label="Baseline"
          sub="fixed T+1 / T+3 / T+5, failure class not consulted"
          records={records}
          arm={baseline}
          budget={budget}
          onHover={setHover}
        />
        <Row
          label="Vasooli"
          sub="diagnose, then spend only where a retry can land"
          records={records}
          arm={sequencer}
          budget={budget}
          onHover={setHover}
        />
      </div>

      <div className="mt-6 flex min-h-[44px] items-center border-t border-rule pt-4">
        {hover ? (
          <p className="verdict animate-[cell-in_0.15s_ease-out]">
            <span className="text-ink">{hover.subscription_id}</span>
            <span className="text-ink-faint"> · </span>
            {hover.bank} · {hover.failure_class.toLowerCase().replace(/_/g, " ")}
            <span className="text-ink-faint"> · </span>
            {hover.sequencer.terminal_reason}
          </p>
        ) : (
          <p className="text-[13px] text-ink-faint">
            Hover any cell to see which subscription it belongs to and what the
            engine decided.
          </p>
        )}
      </div>
    </section>
  );
}
