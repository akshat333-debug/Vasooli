import { rupees, type BatchRecord, type Escalation } from "@/lib/data";

/**
 * The escalation queue — where every rupee the engine declined to chase goes
 * next.
 *
 * This is the half of the product the exception list does not cover. Refusing
 * to debit is only half an answer: the money is still owed, and a system that
 * stops there has replaced one silent failure (burning attempts) with another
 * (a queue nobody works). The route comes from decide.Escalation as structured
 * data, so this component classifies nothing — it renders a decision the engine
 * already made and wrote to the ledger.
 */
export default function EscalationQueue({
  records,
  labels,
}: {
  records: BatchRecord[];
  labels: Record<string, string>;
}) {
  const queue = new Map<Escalation, BatchRecord[]>();
  for (const r of records) {
    if (r.sequencer.recovered) continue;
    const k = (r.sequencer.escalation ?? "NONE") as Escalation;
    queue.set(k, [...(queue.get(k) ?? []), r]);
  }
  const rows = [...queue.entries()]
    .map(([k, items]) => ({
      route: k,
      items,
      value: items.reduce((a, r) => a + r.amount_paise, 0),
    }))
    .sort((a, b) => b.value - a.value);
  const total = rows.reduce((a, r) => a + r.value, 0);
  // The whole point of the queue: every unrecovered rupee must land in a named
  // route. A non-zero figure here would mean the engine had produced a record
  // it refused to act on AND had nothing to say about, which is the failure
  // this section exists to rule out. It is computed, not asserted.
  const unassigned = rows
    .filter((r) => r.route === "NONE")
    .reduce((a, r) => a + r.value, 0);

  const TONE: Record<string, string> = {
    RE_MANDATE_LINK: "#8f8fe8",
    AFA_PAYMENT_LINK: "#b5533f",
    WINBACK_CAMPAIGN: "#d9ac43",
    MANDATE_UPGRADE: "#8fae86",
    HUMAN_REVIEW: "#6f6a60",
  };

  //<-- Short human names for the reconciliation line. The enum reads as shouting
  // in a sentence, and lowercasing it produces "afa payment link", which reads
  // as neither an enum nor English.
  const SHORT: Record<string, string> = {
    RE_MANDATE_LINK: "re-mandate",
    AFA_PAYMENT_LINK: "AFA link",
    WINBACK_CAMPAIGN: "winback",
    MANDATE_UPGRADE: "cap upgrade",
    HUMAN_REVIEW: "human review",
  };

  const OWNER: Record<string, string> = {
    RE_MANDATE_LINK: "Ops",
    AFA_PAYMENT_LINK: "Ops",
    WINBACK_CAMPAIGN: "Growth",
    MANDATE_UPGRADE: "Finance",
    HUMAN_REVIEW: "Support",
  };

  return (
    <section className="overflow-hidden rounded-2xl border border-rule bg-paper-raised">
      <div className="border-b border-rule px-6 py-5 sm:px-8">
        <p className="eyebrow mb-2">Escalation queue</p>
        <h2 className="display text-[20px] font-semibold sm:text-[23px]">
          {rupees(total)} still owed, and a route for every rupee of it.
        </h2>
        <p className="mt-1.5 max-w-2xl text-[13.5px] leading-relaxed text-ink-mute">
          Each route is a field on the decision, not a phrase parsed out of one.
          The baseline produces none of this: it spends the attempts, halts the
          subscription, and says nothing about what to do next.
        </p>
      </div>

      {/* Reconciliation. The arithmetic is shown rather than summarised,
          because "nothing dead-ends" is a claim and a sum is a proof. */}
      <div className="border-b border-rule px-6 py-5 sm:px-8">
        <p className="tnum mb-3 font-mono text-[12.5px] leading-relaxed text-ink-soft">
          {rupees(total)} unrecovered ={" "}
          {rows.map((r, i) => (
            <span key={r.route}>
              {i > 0 ? " + " : ""}
              {rupees(r.value)} {SHORT[r.route] ?? r.route}
            </span>
          ))}
          {" + "}
          <span className={unassigned === 0 ? "font-semibold text-ink" : "text-clay-ink"}>
            {rupees(unassigned)} unassigned
          </span>
        </p>

        <div
          className="flex h-3 w-full overflow-hidden rounded-[2px]"
          role="img"
          aria-label={`Unrecovered value by route: ${rows
            .map((r) => `${r.route} ${rupees(r.value)}`)
            .join(", ")}. Unassigned ${rupees(unassigned)}.`}
        >
          {rows.map((r) => (
            <div
              key={r.route}
              title={`${r.route} — ${rupees(r.value)}`}
              style={{
                width: `${(r.value / total) * 100}%`,
                background: TONE[r.route] ?? "#9a9488",
              }}
            />
          ))}
        </div>

        <p className="mt-3 text-[13px] leading-relaxed text-ink-mute">
          {unassigned === 0 ? (
            <>
              <strong className="font-semibold text-ink-soft">
                Nothing is unassigned.
              </strong>{" "}
              Every rupee the engine declined to chase has a route attached as a
              field on the decision, so the queue reconciles to the total exactly.
            </>
          ) : (
            <>
              {rupees(unassigned)} has no route attached. That is a defect, not a
              category.
            </>
          )}
        </p>
      </div>

      <ul className="px-6 py-2 sm:px-8">
        {rows.map(({ route, items, value }) => (
          <li
            key={route}
            className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-rule/50 py-3.5 last:border-0"
          >
            <span className="tnum w-8 shrink-0 text-[15px] font-semibold">
              {items.length}
            </span>
            <span className="tnum w-28 shrink-0 text-[13px] text-ink-mute">
              {rupees(value)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-mono text-[12px] tracking-tight text-ink">
                  {route}
                </span>
                <span className="rounded bg-paper-sunk px-1.5 py-px font-mono text-[10.5px] text-ink-soft">
                  {OWNER[route] ?? "Unassigned"}
                </span>
              </span>
              <span className="mt-0.5 block text-[12.5px] text-ink-mute">
                {labels[route] ?? "no route assigned"}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
