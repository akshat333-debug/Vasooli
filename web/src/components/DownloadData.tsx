"use client";

import { type BatchRecord } from "@/lib/data";

/**
 * Hand over the underlying rows.
 *
 * A dashboard that shows conclusions and withholds the data behind them asks to
 * be trusted. Offering the file is the cheapest way to stop asking: a reader who
 * suspects a figure can open the CSV and recompute it, and one who does not can
 * ignore this entirely. Built in the browser from the same batch.json the page
 * renders, so the download cannot disagree with what is on screen.
 *
 * `seed` arrives as a prop rather than being imported from lib/data. Importing
 * it there pulled the whole 480 KB batch payload into the records page's CLIENT
 * bundle for the sake of one number in a filename, taking its first-load JS
 * from 105 KB to 147 KB. The rows are already handed down as props by the
 * server component; the seed travels the same way.
 */

const COLUMNS: { key: string; get: (r: BatchRecord) => string | number }[] = [
  { key: "subscription_id", get: (r) => r.subscription_id },
  { key: "customer_id", get: (r) => r.customer_id },
  { key: "bank", get: (r) => r.bank },
  { key: "amount_inr", get: (r) => (r.amount_paise / 100).toFixed(2) },
  { key: "error_code", get: (r) => r.error_code },
  { key: "error_reason", get: (r) => r.error_reason },
  { key: "failure_class", get: (r) => r.failure_class },
  { key: "diagnosis_source", get: (r) => r.diagnosis_source },
  { key: "mandate_status", get: (r) => r.mandate_status },
  { key: "attempts_used", get: (r) => r.attempts_used },
  { key: "rule_fired", get: (r) => r.rule_fired },
  { key: "action", get: (r) => r.action },
  { key: "escalation", get: (r) => r.escalation },
  { key: "scheduled_at", get: (r) => r.scheduled_at ?? "" },
  { key: "expected_success", get: (r) => r.expected_success ?? "" },
  { key: "baseline_recovered", get: (r) => String(r.baseline.recovered) },
  { key: "baseline_attempts_spent", get: (r) => r.baseline.attempts_spent },
  { key: "vasooli_recovered", get: (r) => String(r.sequencer.recovered) },
  { key: "vasooli_attempts_spent", get: (r) => r.sequencer.attempts_spent },
  { key: "vasooli_attempts_preserved", get: (r) => r.sequencer.attempts_preserved },
  { key: "verdict", get: (r) => r.verdict },
];

function csv(records: BatchRecord[]): string {
  const esc = (v: string | number) => {
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [
    COLUMNS.map((c) => c.key).join(","),
    ...records.map((r) => COLUMNS.map((c) => esc(c.get(r))).join(",")),
  ].join("\n");
}

export default function DownloadData({
  records,
  seed,
  label = "Download these rows as CSV",
}: {
  records: BatchRecord[];
  seed: number;
  label?: string;
}) {
  const download = () => {
    const blob = new Blob([csv(records)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `vasooli-batch${seed}-${records.length}-records.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <button
      onClick={download}
      className="rounded-lg border border-rule px-3 py-1.5 text-[12.5px] text-ink-soft transition-colors hover:border-ink-faint"
    >
      {label} ({records.length})
    </button>
  );
}
