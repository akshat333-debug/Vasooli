import AttemptLedger from "@/components/AttemptLedger";
import ExceptionList from "@/components/ExceptionList";
import { batch, rupees } from "@/lib/data";

export default function BatchPage() {
  const { arms, records, meta, ledger } = batch;
  const bl = arms.baseline;
  const sq = arms.sequencer;

  const perAttemptGain =
    ((sq.paise_per_attempt - bl.paise_per_attempt) / bl.paise_per_attempt) * 100;
  const attemptsSaved = bl.attempts_spent - sq.attempts_spent;
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
          fix, and spends what is left where it can actually land — inside the
          RBI e-mandate envelope, with every decision written to an audit trail.
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
          label="Recovered per attempt"
          value={rupees(Math.round(sq.paise_per_attempt))}
          delta={`+${perAttemptGain.toFixed(0)}% vs baseline`}
          note={`Baseline ${rupees(Math.round(bl.paise_per_attempt))}. The retry budget is the scarce resource, so this is the number that matters.`}
        />
        <Stat
          tone="periwinkle"
          label="Attempts preserved"
          value={String(preserved)}
          delta={`${attemptsSaved} fewer spent than baseline`}
          note="Retries the engine declined to spend on debits that could not have succeeded. Invisible in any report that only counts wins."
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
            <p className="eyebrow mb-3 !text-clay">Why the raw totals disagree</p>
            <h2 className="display text-[21px] leading-snug font-semibold sm:text-[25px]">
              On gross recovery the baseline wins. It wins by making a debit it
              is not allowed to make.
            </h2>
            <p className="mt-4 text-[14.5px] leading-relaxed text-ink-soft">
              {rupees(bl.recovered_above_cap_paise, { decimals: true })} of the
              baseline&rsquo;s total came from a single unattended debit above
              the RBI e-mandate standard cap of ₹15,000. No merchant may bank
              that as recovered revenue — it is a compliance failure wearing a
              recovery number&rsquo;s clothes. Strip it out and the ranking
              inverts on both axes.
            </p>
          </div>

          <div className="space-y-3 self-center">
            <Compare
              label="Within the envelope"
              baseline={bl.recovered_within_envelope_paise}
              sequencer={sq.recovered_within_envelope_paise}
            />
            <Compare
              label="Above the cap"
              baseline={bl.recovered_above_cap_paise}
              sequencer={sq.recovered_above_cap_paise}
              breach
            />
          </div>
        </div>
      </section>

      <div className="rise mb-8" style={{ animationDelay: "240ms" }}>
        <ExceptionList records={records} />
      </div>

      {/* ---- Provenance ---- */}
      <section className="rise grid gap-4 md:grid-cols-2" style={{ animationDelay: "300ms" }}>
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
            is a deterministic scorer — reproducible, testable, explainable to a
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
      <p className="tnum mt-2 text-[12.5px] font-medium text-ink-mute">{delta}</p>
      <p className="mt-3 border-t border-ink/8 pt-3 text-[12.5px] leading-relaxed text-ink-mute">
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
}: {
  label: string;
  baseline: number;
  sequencer: number;
  breach?: boolean;
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
                breach && (v as number) > 0 ? "text-clay" : "text-ink"
              }`}
            >
              {rupees(v as number)}
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
