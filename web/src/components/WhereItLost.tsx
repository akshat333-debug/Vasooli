import { rupees, type BatchRecord } from "@/lib/data";

/**
 * Where Vasooli lost to the baseline.
 *
 * Every recovery report shows its wins. This shows the records the naive arm
 * recovered and this one did not, because a comparison that only reports the
 * favourable direction is not a comparison. It is also checkable: the two
 * figures below net to the headline delta exactly, so a reader can verify the
 * whole claim with one subtraction rather than trusting the summary.
 *
 * These are not refusals. Every one is a record Vasooli DID schedule -- rule 8,
 * a live mandate, a recoverable failure -- where the moment it chose lost to
 * the baseline's fixed schedule on the same random draw. That is the honest
 * shape of the loss: the timing model is a model, and sometimes T+1 happens to
 * be the better guess.
 */
export default function WhereItLost({
  records,
  deltaPaise,
}: {
  records: BatchRecord[];
  deltaPaise: number;
}) {
  const lost = records
    .filter((r) => r.baseline.recovered && !r.sequencer.recovered)
    .sort((a, b) => b.amount_paise - a.amount_paise);
  const won = records.filter((r) => !r.baseline.recovered && r.sequencer.recovered);
  const lostValue = lost.reduce((a, r) => a + r.amount_paise, 0);
  const wonValue = won.reduce((a, r) => a + r.amount_paise, 0);

  if (lost.length === 0) return null;

  return (
    <section className="overflow-hidden rounded-2xl border border-rule bg-paper-raised">
      <div className="border-b border-rule px-6 py-5 sm:px-8">
        <p className="eyebrow mb-2">Where Vasooli lost</p>
        <h2 className="display text-[20px] font-semibold sm:text-[23px]">
          The baseline recovered {lost.length} records this arm did not.
        </h2>
        <p className="mt-1.5 max-w-2xl text-[13.5px] leading-relaxed text-ink-mute">
          None of these was refused. Every one was scheduled by rule 8 against a
          live mandate, and the moment this engine chose lost to the
          baseline&rsquo;s fixed schedule on the same draw. The timing model is a
          model; sometimes T+1 is the better guess.
        </p>
      </div>

      <div className="overflow-x-auto px-6 py-4 sm:px-8">
        <table className="w-full min-w-[440px] text-[13px]">
          <thead>
            <tr className="border-b border-rule text-[11px] tracking-wider text-ink-faint uppercase">
              <th className="py-2 text-left font-normal">Subscription</th>
              <th className="py-2 text-left font-normal">Failure</th>
              <th className="py-2 text-right font-normal">Amount</th>
            </tr>
          </thead>
          <tbody>
            {lost.map((r) => (
              <tr key={r.subscription_id} className="border-b border-rule/50 last:border-0">
                <td className="py-2 font-mono text-[12px]">{r.subscription_id}</td>
                <td className="py-2 text-ink-mute">
                  {r.failure_class.toLowerCase().replace(/_/g, " ")}
                </td>
                <td className="tnum py-2 text-right">
                  {rupees(r.amount_paise, { decimals: true })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* The point of the section. A reader can check the headline from here. */}
      <div className="border-t border-rule bg-paper-sunk/40 px-6 py-4 sm:px-8">
        <p className="mb-2 text-[11px] tracking-wider text-ink-faint uppercase">
          It reconciles
        </p>
        <p className="tnum font-mono text-[13px] leading-relaxed text-ink-soft">
          {rupees(wonValue, { decimals: true })} won ({won.length} record
          {won.length === 1 ? "" : "s"}) &minus;{" "}
          {rupees(lostValue, { decimals: true })} lost ({lost.length} records) ={" "}
          <span className="font-semibold text-ink">
            {rupees(deltaPaise, { decimals: true })}
          </span>
        </p>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-mute">
          That is the entire headline recovery delta, accounted for record by
          record. The gap between the arms is not built out of the rupees
          recovered — it is built out of the{" "}
          <strong className="font-semibold text-ink-soft">attempts saved</strong>{" "}
          getting there, which is why recovery per attempt is the metric and
          gross recovery is not.
        </p>
        {/* The choice of metric is the objection this project is most exposed
            to, so the number that makes it uncomfortable is printed here rather
            than left to be discovered. Source: `vasooli experiments --seeds 40`
            section 1c, seeds 1-40, same sweep as the ablation table. */}
        <p className="mt-3 rounded-lg border border-rule bg-paper px-3.5 py-3 text-[12.5px] leading-relaxed text-ink-mute">
          <strong className="font-semibold text-ink-soft">
            And the crude question, since choosing a metric is exactly where a
            reader should be suspicious:
          </strong>{" "}
          which arm simply collected more money, budget ignored? Across 40 seeds
          the sequencer wins that one in{" "}
          <strong className="font-semibold text-ink-soft">25</strong>, ties 1 and
          loses 14 — median <span className="tnum">+₹1,047</span>, worst seed{" "}
          <span className="tnum">−₹12,695</span>. That is the weakest number in
          this project and <code className="font-mono">vasooli experiments</code>{" "}
          prints it unprompted. The argument for the rate is that the budget is
          three deep and does not refill, so the arm that collects the same money
          on half of it starts next cycle with something left. Judge that claim
          on the rate; the total is here so the choice is visible rather than
          convenient.
        </p>
      </div>
    </section>
  );
}
