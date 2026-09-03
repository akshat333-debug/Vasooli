"use client";

import { useState } from "react";
import { rupees, type Scenario } from "@/lib/data";

/**
 * Policy variations, each one a real engine run.
 *
 * Nothing here is projected or interpolated. Every row was produced by running
 * the batch again with that policy, which is why the numbers can be trusted the
 * same way the headline can — and why the interface has no "what if" slider.
 * A slider would have to compute an outcome the engine never produced.
 */
export default function Scenarios({ scenarios }: { scenarios: Scenario[] }) {
  const base = scenarios[0];
  const [selected, setSelected] = useState(scenarios[1]?.id ?? scenarios[0].id);
  const active = scenarios.find((s) => s.id === selected) ?? base;
  const isBase = active.id === base.id;

  const rows: [string, number, number, boolean][] = [
    ["Recovered, within envelope", base.recovered_within_envelope_paise,
      active.recovered_within_envelope_paise, true],
    ["Recovered per attempt", Math.round(base.adjusted_paise_per_attempt),
      Math.round(active.adjusted_paise_per_attempt), true],
    ["Attempts spent", base.attempts_spent, active.attempts_spent, false],
    ["Wasted attempts", base.wasted_attempts, active.wasted_attempts, false],
    ["Debited above the RBI cap", base.recovered_above_cap_paise,
      active.recovered_above_cap_paise, true],
  ];

  return (
    <section className="overflow-hidden rounded-2xl border border-rule bg-paper-raised">
      <div className="border-b border-rule px-6 py-5 sm:px-8">
        <p className="eyebrow mb-2">What each rule is holding back</p>
        <h2 className="display text-[20px] font-semibold sm:text-[23px]">
          Change the policy, run it again, see the cost.
        </h2>
        <p className="mt-1.5 max-w-2xl text-[13.5px] leading-relaxed text-ink-mute">
          Every option below is a real batch the engine ran, not a projection.
          Compared against the shipped policy on identical records and draws.
        </p>
      </div>

      <div className="flex flex-wrap gap-1.5 border-b border-rule px-6 py-3.5 sm:px-8">
        {scenarios.slice(1).map((s) => (
          <button
            key={s.id}
            onClick={() => setSelected(s.id)}
            aria-pressed={selected === s.id}
            className={`rounded-lg border px-3 py-1.5 text-[12.5px] transition-colors ${
              selected === s.id
                ? "border-ink bg-ink text-paper"
                : "border-rule text-ink-soft hover:border-ink-faint"
            }`}
          >
            {s.name}
          </button>
        ))}
      </div>

      <div className="px-6 py-5 sm:px-8">
        <p className="verdict mb-4">{active.note}</p>

        {active.truncated && (
          <p className="mb-4 rounded-lg border border-clay/40 bg-clay-soft/30 px-4 py-3 text-[13px] leading-relaxed">
            <strong className="font-semibold">This run did not finish.</strong> The
            breaker stopped it after {active.records_processed} of 100 records, so
            its totals are computed over a prefix of the batch. Shown deliberately:
            a truncated run is what the guardrail doing its job looks like, and the
            report refuses to present it as a result.
          </p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-[13.5px]">
            <thead>
              <tr className="border-b border-rule text-[11px] tracking-wider text-ink-faint uppercase">
                <th className="py-2 text-left font-normal">Measure</th>
                <th className="py-2 text-right font-normal">As shipped</th>
                <th className="py-2 text-right font-normal">{active.name}</th>
                <th className="py-2 text-right font-normal">Change</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([label, b, a, money]) => {
                const delta = a - b;
                // The only measure where a rise is unambiguously bad, because
                // it is not revenue at all — it is a debit outside the envelope.
                const breach = label.includes("above the RBI cap") && a > 0;
                const fmt = (v: number) =>
                  money ? rupees(v) : String(v);
                return (
                  <tr key={label} className="border-b border-rule/50 last:border-0">
                    <td className="py-2.5 text-ink-soft">{label}</td>
                    <td className="tnum py-2.5 text-right">{fmt(b)}</td>
                    <td
                      className={`tnum py-2.5 text-right font-medium ${
                        breach ? "text-clay-ink" : ""
                      }`}
                    >
                      {fmt(a)}
                    </td>
                    <td
                      className={`tnum py-2.5 text-right ${
                        delta === 0
                          ? "text-ink-faint"
                          : breach
                            ? "text-clay-ink"
                            : "text-ink-mute"
                      }`}
                    >
                      {delta === 0 ? "No change" : `${delta > 0 ? "+" : "−"}${fmt(Math.abs(delta))}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {isBase && (
          <p className="mt-4 text-[13px] text-ink-faint">
            Pick a variation above to see what removing a rule costs.
          </p>
        )}
      </div>
    </section>
  );
}
