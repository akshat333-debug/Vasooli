import AttemptLedger from "@/components/AttemptLedger";
import DecisionTrace from "@/components/DecisionTrace";
import EscalationQueue from "@/components/EscalationQueue";
import ExceptionList from "@/components/ExceptionList";
import WhereItLost from "@/components/WhereItLost";
import Scenarios from "@/components/Scenarios";
import { batch, rupees, type Arm } from "@/lib/data";

export default function BatchPage() {
  const { arms, records, meta, ledger } = batch;
  const bl = arms.baseline;
  const sq = arms.sequencer;

  // Compliance-adjusted on BOTH sides. Using the raw figures here would put
  // the above-cap debits back into the baseline's numerator while the recovered
  // row beside it excludes them — two bases in one comparison, which is the
  // exact bug this was caught making in the text report.
  const blPer = bl.adjusted_paise_per_attempt;
  const sqPer = sq.adjusted_paise_per_attempt;
  const perAttemptGain = ((sqPer - blPer) / blPer) * 100;
  // The number this project is actually about. Both arms recover within 2.3%
  // of each other THIS cycle; what separates them is how many recoverable
  // subscriptions each one drove to `halted`, because a spent retry budget is
  // permanent. Leading with recovery-per-attempt invited the fair objection
  // that a ratio was doing the work.
  const haltedValue = (a: Arm) =>
    a.pushed_to_halt.reduce((t, o) => t + o.amount_paise, 0);
  const recurringSaved = haltedValue(bl) - haltedValue(sq);
  const subsSaved = bl.pushed_to_halt.length - sq.pushed_to_halt.length;
  const attemptsSaved = bl.attempts_spent - sq.attempts_spent;
  // The rule-6 record: above the RBI cap, refused by three independent layers,
  // and the clearest single illustration of the whole mechanism. Falls back to
  // the first refusal of any kind so this never renders empty on another batch.
  const traced =
    records.find((r) => r.rule_fired === 6) ??
    records.find((r) => r.action !== "RETRY_SCHEDULED") ??
    records[0];
  const tracedHash =
    ledger.entries.find(
      (e) => e.subscription_id === traced.subscription_id && e.event === "decision",
    )?.hash ?? null;

  const preserved = sq.outcomes
    .filter((o) => !o.recovered)
    .reduce((a, o) => a + o.attempts_preserved, 0);

  return (
    <div className="mx-auto max-w-[1180px] px-5 py-8 sm:px-8 sm:py-12">
      {/* ---- Hero: the thesis, not a vanity total ---- */}
      <header className="rise mb-10">
        <p className="eyebrow mb-3">
          Batch {meta.seed} · {meta.record_count} at-risk subscriptions ·{" "}
          {rupees(sq.value_at_risk_paise)} at risk
        </p>
        <h1 className="display max-w-3xl text-[30px] leading-[1.12] font-semibold tracking-tight sm:text-[44px]">
          A failed debit gives you three attempts.
          <br />
          <span className="text-ink-mute">Then the subscription is gone.</span>
        </h1>
        <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-ink-soft sm:text-[16px]">
          Most dunning systems spend those three on a fixed schedule and hope.
          Vasooli diagnoses each failure first, refuses the ones no retry can
          fix, and spends what is left where it can actually land, inside the
          RBI e-mandate envelope, with every decision written to an audit trail.
        </p>
        <p className="mt-4 max-w-2xl text-[15px] leading-relaxed sm:text-[16px]">
          On this batch it recovers{" "}
          <strong className="font-semibold">the same money</strong> as the fixed
          schedule while spending{" "}
          <strong className="font-semibold">half the retry budget</strong> — and
          leaves {subsSaved} more subscriptions alive, worth{" "}
          <strong className="font-semibold">{rupees(recurringSaved)} a month</strong>{" "}
          of recurring revenue the baseline destroys.
        </p>
      </header>

      {/* ---- Signature ---- */}
      <div className="rise mb-8" style={{ animationDelay: "60ms" }}>
        <AttemptLedger
          records={records}
          baseline={bl}
          sequencer={sq}
          budget={meta.retry_budget_per_record}
        />
      </div>

      {/* ---- The three facts that matter ---- */}
      <section className="rise mb-8 grid gap-4 md:grid-cols-3" style={{ animationDelay: "120ms" }}>
        <Stat
          tone="sage"
          label="Recurring revenue kept alive"
          value={`${rupees(recurringSaved)}/mo`}
          delta={`${subsSaved} fewer subscriptions killed`}
          note={`Recoverable subscriptions each arm drove to halted: baseline ${bl.pushed_to_halt.length}, here ${sq.pushed_to_halt.length}. A spent retry budget is permanent, so this repeats every month — against a one-cycle recovery difference of ${rupees(sq.recovered_within_envelope_paise - bl.recovered_within_envelope_paise)}.`}
        />
        <Stat
          tone="periwinkle"
          label="Attempts preserved"
          value={String(preserved)}
          delta={`${attemptsSaved} fewer spent than baseline`}
          note={`Retries the engine declined to spend on debits that could not have succeeded. Worth ${rupees(Math.round(sqPer))} each here against the baseline's ${rupees(Math.round(blPer))} — ${perAttemptGain.toFixed(0)}% more per attempt — but the point is the budget they leave intact.`}
        />
        <Stat
          tone="mustard"
          label="Sent to a person"
          value={String(records.filter((r) => r.action === "HUMAN_REVIEW").length)}
          delta="not auto-actioned"
          note="Above the RBI cap, above the mandate's own limit, or unclassifiable. Escalation is the product working, not a failure."
        />
      </section>

      {/* ---- The compliance finding. This is the slot Zarss used to upsell. ---- */}
      <section
        className="rise mb-8 overflow-hidden rounded-2xl border border-clay/35 bg-clay-soft/35"
        style={{ animationDelay: "180ms" }}
      >
        <div className="grid gap-6 p-6 sm:p-8 lg:grid-cols-[1.35fr_1fr] lg:gap-10">
          <div>
            <p className="eyebrow mb-3 !text-clay-ink">Three layers, one answer</p>
            <h2 className="display text-[21px] leading-snug font-semibold sm:text-[25px]">
              The baseline burned {bl.breaker_refusals} attempts on debits the
              network was never going to settle.
            </h2>
            <p className="mt-4 text-[14.5px] leading-relaxed text-ink-soft">
              Above ₹15,000 the RBI e-mandate framework requires additional
              factor authentication, so an unattended presentation is declined.
              Three independent layers refuse it here: the stopping rule
              declines to schedule it, the money-side breaker refuses it at the
              action boundary, and the simulated world declines it on
              presentation. Both arms therefore recover{" "}
              {rupees(sq.recovered_above_cap_paise, { decimals: true })} above
              the cap &mdash; which is why the raw and compliance-adjusted
              numbers on this page are identical, and why there is no
              adjustment left to argue about.
            </p>
            <p className="mt-3 text-[13.5px] leading-relaxed text-ink-soft">
              An earlier build credited the baseline with{" "}
              <span className="tnum">₹73,653.24</span> of above-cap recoveries
              and subtracted them in the report. That made the compliance
              headline a correction to a simulator bug rather than a
              measurement of behaviour. It is logged as defect 19.
            </p>
          </div>

          <div className="space-y-3 self-center">
            <Compare
              label="Recovered"
              baseline={bl.recovered_within_envelope_paise}
              sequencer={sq.recovered_within_envelope_paise}
            />
            <Compare
              label="Refused by the breaker"
              baseline={bl.breaker_refusals}
              sequencer={sq.breaker_refusals}
              breach
              unit="count"
            />
            <Compare
              label="Recoverable subs halted"
              baseline={bl.pushed_to_halt.length}
              sequencer={sq.pushed_to_halt.length}
              breach
              unit="count"
            />
          </div>
        </div>
      </section>

      <div className="rise mb-8" style={{ animationDelay: "240ms" }}>
        <Scenarios scenarios={batch.scenarios} />
      </div>

      <div className="rise mb-8" style={{ animationDelay: "300ms" }}>
        <EscalationQueue records={records} labels={batch.escalation_labels} />
      </div>

      <div className="rise mb-8" style={{ animationDelay: "330ms" }}>
        <WhereItLost
          records={records}
          deltaPaise={
            sq.recovered_within_envelope_paise - bl.recovered_within_envelope_paise
          }
        />
      </div>

      <div className="rise mb-8" style={{ animationDelay: "360ms" }}>
        <DecisionTrace record={traced} ledgerHash={tracedHash} />
      </div>

      <div className="rise mb-8" style={{ animationDelay: "390ms" }}>
        <ExceptionList
          records={records}
          escalationLabels={batch.escalation_labels}
        />
      </div>

      {/* ---- Provenance ---- */}
      <section className="rise grid gap-4 md:grid-cols-2" style={{ animationDelay: "420ms" }}>
        <div className="rounded-2xl border border-rule bg-paper-raised p-6">
          <p className="eyebrow mb-3">Audit trail</p>
          <div className="flex items-baseline gap-2.5">
            <span className="display tnum text-[28px] font-semibold">{ledger.rows}</span>
            <span className="text-[13px] text-ink-mute">hash-chained rows</span>
          </div>
          <p className="verdict mt-3">
            <span
              className="mr-2 inline-block h-2 w-2 rounded-full align-middle"
              style={{ background: ledger.verified ? "#8fae86" : "#b5533f" }}
            />
            {ledger.detail}
          </p>
          <p className="mt-3 text-[13px] leading-relaxed text-ink-mute">
            Every decision above is written to an append-only chain before it is
            acted on. Editing any historical row breaks every hash after it, and
            verification reports the first broken index rather than a bare pass
            or fail.
          </p>
        </div>

        <div className="rounded-2xl border border-rule bg-paper-raised p-6">
          <p className="eyebrow mb-3">Where the model sits</p>
          <p className="text-[14.5px] leading-relaxed text-ink-soft">
            A language model reads free-text bank error descriptions, which is a
            genuine language problem. It is allowed to answer{" "}
            <span className="font-mono text-[13px]">UNKNOWN</span>, and{" "}
            <span className="font-mono text-[13px]">UNKNOWN</span> goes to a
            person.
          </p>
          <p className="mt-3 border-l-2 border-ink pl-3 text-[14.5px] leading-relaxed font-medium">
            No language model participates in any decision to move money. Timing
            is a deterministic scorer: reproducible, testable, explainable to a
            regulator.
          </p>
        </div>
      </section>
    </div>
  );
}

function Stat({
  tone,
  label,
  value,
  delta,
  note,
}: {
  tone: "sage" | "periwinkle" | "mustard";
  label: string;
  value: string;
  delta: string;
  note: string;
}) {
  const bg = {
    sage: "bg-sage-soft/55",
    periwinkle: "bg-periwinkle-soft/45",
    mustard: "bg-mustard-soft/45",
  }[tone];
  const dot = { sage: "#8fae86", periwinkle: "#8f8fe8", mustard: "#d9ac43" }[tone];

  return (
    <div className={`rounded-2xl border border-rule/70 ${bg} p-5`}>
      <div className="mb-3 flex items-center gap-2">
        <span className="h-2 w-2 rounded-full" style={{ background: dot }} />
        <p className="text-[12.5px] font-medium text-ink-soft">{label}</p>
      </div>
      <p className="display tnum text-[34px] leading-none font-semibold">{value}</p>
      {/* ink-soft, not ink-mute: these sit on a tinted card, which is darker
          than paper and drops ink-mute to ~4.2:1, under the AA floor. */}
      <p className="tnum mt-2 text-[12.5px] font-medium text-ink-soft">{delta}</p>
      <p className="mt-3 border-t border-ink/8 pt-3 text-[12.5px] leading-relaxed text-ink-soft">
        {note}
      </p>
    </div>
  );
}

function Compare({
  label,
  baseline,
  sequencer,
  breach = false,
  // Counts (refusals, halted subscriptions) are not money and must not be
  // formatted as rupees -- "3" refusals rendered as a currency reads as value
  // recovered, which is the opposite of what it is.
  unit = "money",
}: {
  label: string;
  baseline: number;
  sequencer: number;
  breach?: boolean;
  unit?: "money" | "count";
}) {
  const max = Math.max(baseline, sequencer, 1);
  return (
    <div className="rounded-xl bg-paper-raised/80 p-4">
      <p className="mb-2.5 text-[12px] font-medium text-ink-mute">{label}</p>
      {[
        ["Baseline", baseline],
        ["Vasooli", sequencer],
      ].map(([name, v]) => (
        <div key={name as string} className="mb-2 last:mb-0">
          <div className="mb-1 flex items-baseline justify-between gap-3">
            <span className="text-[12px] text-ink-mute">{name}</span>
            <span
              className={`tnum text-[13px] font-semibold ${
                breach && (v as number) > 0 ? "text-clay-ink" : "text-ink"
              }`}
            >
              {unit === "money" ? rupees(v as number) : String(v)}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-ink/8">
            <div
              className="h-full rounded-full"
              style={{
                width: `${Math.max(((v as number) / max) * 100, (v as number) > 0 ? 3 : 0)}%`,
                background: breach ? "#b5533f" : "#1c1b19",
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
