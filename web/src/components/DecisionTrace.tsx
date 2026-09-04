import { rupees, type BatchRecord } from "@/lib/data";

/**
 * One subscription, all the way through, in five steps.
 *
 * The rest of the page argues in aggregate. This is the mechanism: a raw string
 * a bank wrote, the class it was resolved to, the rules that ran, the refusal or
 * the slot, and the ledger row that records it. If a reader believes this one
 * record, the aggregate is just this repeated a hundred times; if they do not,
 * no headline will convince them.
 *
 * The record is chosen at render from the batch rather than hard-coded, so this
 * cannot drift out of step with the data the way a pasted screenshot would.
 */
export default function DecisionTrace({
  record,
  ledgerHash,
}: {
  record: BatchRecord;
  ledgerHash: string | null;
}) {
  const r = record;
  const steps: { label: string; body: React.ReactNode }[] = [
    {
      label: "What the bank sent",
      body: (
        <>
          <p className="font-mono text-[11.5px] text-ink-faint">
            {r.error_code} / {r.error_reason}
          </p>
          <p className="mt-1 text-[12.5px] leading-snug">{r.error_description}</p>
        </>
      ),
    },
    {
      label: "Classified",
      body: (
        <>
          <p className="font-mono text-[12px]">{r.failure_class}</p>
          <p className="mt-1 text-[12.5px] leading-snug text-ink-mute">
            via {r.diagnosis_source}
          </p>
        </>
      ),
    },
    {
      label: "Rules evaluated",
      body: (
        <>
          <div className="flex flex-wrap gap-1">
            {[1, 2, 3, 4, 5, 6, 7].map((n) => (
              <span
                key={n}
                className={`tnum inline-flex h-5 w-5 items-center justify-center rounded font-mono text-[11px] ${
                  n === r.rule_fired
                    ? "bg-ink text-paper"
                    : n < r.rule_fired
                      ? "bg-paper-sunk text-ink-soft"
                      : "text-ink-mute"
                }`}
              >
                {n}
              </span>
            ))}
          </div>
          <p className="mt-1.5 text-[12.5px] leading-snug text-ink-mute">
            {r.rule_fired === 8
              ? "all seven passed"
              : `rule ${r.rule_fired} fired`}
          </p>
        </>
      ),
    },
    {
      label: r.scheduled_at ? "Scheduled" : "Refused",
      body: (
        <>
          <p className="font-mono text-[12px]">
            {r.scheduled_at
              ? new Date(r.scheduled_at).toISOString().slice(0, 16).replace("T", " ")
              : r.action}
          </p>
          <p className="mt-1 text-[12.5px] leading-snug text-ink-mute">
            {r.expected_success !== null
              ? `assumed p=${r.expected_success.toFixed(2)}`
              : r.escalation.toLowerCase().replace(/_/g, " ")}
          </p>
        </>
      ),
    },
    {
      label: "Written to the ledger",
      body: (
        <>
          <p className="font-mono text-[11.5px] break-all text-ink-faint">
            {ledgerHash ? ledgerHash.slice(0, 16) + "…" : "—"}
          </p>
          <p className="mt-1 text-[12.5px] leading-snug text-ink-mute">
            before anything was attempted
          </p>
        </>
      ),
    },
  ];

  return (
    <section className="overflow-hidden rounded-2xl border border-rule bg-paper-raised">
      <div className="border-b border-rule px-6 py-5 sm:px-8">
        <p className="eyebrow mb-2">One decision, end to end</p>
        <h2 className="display text-[20px] font-semibold sm:text-[23px]">
          {r.subscription_id} · {rupees(r.amount_paise, { decimals: true })}
        </h2>
        <p className="mt-1.5 max-w-2xl text-[13.5px] leading-relaxed text-ink-mute">
          Everything above this is an aggregate. This is the mechanism it
          aggregates, for one subscription, in the order it actually happened.
        </p>
      </div>

      <div className="scroll-slim overflow-x-auto px-6 py-6 sm:px-8">
        <ol className="flex min-w-[840px] items-stretch gap-0">
          {steps.map((s, i) => (
            <li key={s.label} className="flex flex-1 items-stretch">
              <div className="min-w-0 flex-1 pr-4">
                <p className="mb-2 text-[10.5px] tracking-wider text-ink-faint uppercase">
                  {s.label}
                </p>
                {s.body}
              </div>
              {i < steps.length - 1 && (
                <div className="mr-4 w-px shrink-0 bg-rule" aria-hidden />
              )}
            </li>
          ))}
        </ol>
      </div>

      <div className="border-t border-rule bg-paper-sunk/40 px-6 py-3.5 sm:px-8">
        <p className="verdict">{r.verdict}</p>
      </div>
    </section>
  );
}
