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
              <span className="block font-mono text-[12px] tracking-tight text-ink">
                {route}
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
