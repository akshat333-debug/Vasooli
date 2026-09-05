import { batch } from "@/lib/data";

export const metadata = { title: "Method · Vasooli" };

const AI_TABLE = [
  ["Detect at-risk", "Rules", false, "Deterministic. A model here is a liability with no upside."],
  ["Classify the failure", "Claude Haiku", true, "Free text, bank-specific, open vocabulary. A genuine language problem."],
  ["Decide retry timing", "No model", false, "Non-determinism in a money decision is indefensible."],
  ["Draft the customer nudge", "Claude Haiku", true, "Hinglish register. Guardrailed, and there is no send path in the module."],
  ["Enforce the limits", "No model", false, "A guardrail a model can argue past is not a guardrail."],
] as const;

const FINDINGS = [
  {
    t: "The scheduler could create the very thing the engine refuses",
    d: "Retry timing searched a window bounded only by the notice period, never by the mandate's expiry. Given a mandate dying in two days and a replenishment cycle eight days out, it scheduled the retry six days after the mandate was dead, reporting a confident p=0.62 for a debit the bank would reject. The stopping rules caught dead mandates on the way in; the scheduler manufactured one on the way out.",
  },
  {
    t: "A fault in the AI guardrail could kill the money stage",
    d: "The circuit breaker wrapped the whole diagnosis loop. Any trip or internal fault propagated out and destroyed the entire batch, including every money decision that never needed a model at all. A guardrail that can take down more than it protects is worse than the thing it guards against.",
  },
  {
    t: "The model's work never reached the decision",
    d: "The run classified the batch with Claude, printed statistics about it, then each arm silently re-ran the dictionary alone and discarded the model's output. One record the model correctly identified as a revoked mandate was still decided as unclassified. The claim that the model was load-bearing was, in the run path, not true.",
  },
  {
    t: "A truncated run rendered as a complete one",
    d: "When the batch breaker tripped, the run stopped at 19 of 100 records and the report printed a full headline comparison, computing rates against a denominator of all 100. It now refuses to present a truncated run as a result.",
  },
  {
    t: "An unreachable model was scored as disagreement",
    d: "With the gateway down, the run reported 20 disagreements, as if a working model had given 20 different answers, rather than 24 failed calls. An accuracy signal computed from calls that never happened is a lie. Unreachable is now counted separately, and a trip surfaces instead of being swallowed.",
  },
  {
    t: "My headline rested on a bug in my own simulator",
    d: "The strongest claim on this page used to be that the baseline only wins on raw totals by making debits above the RBI cap. An external reviewer pointed out that above \u20b915,000 the debit needs additional factor authentication, so the bank declines it \u2014 that money was never deliverable, and the attempt layer was crediting it anyway. The compliance adjustment was correcting my own bug rather than measuring a behaviour. Fixed, the finding got sharper: the baseline was not merely breaking a rule, it was burning attempts on debits that could never settle. Raw and adjusted now coincide.",
  },
  {
    t: "The money breaker advertised two limits it never applied",
    d: "RecoveryPolicy declared a per-debit cap of \u20b915,000 and a three-attempt budget, both with comments saying they must never be exceeded, and enforced neither. Neither field was read anywhere in the engine. This was the third instance of the same shape in the log, after an inert cost limit and a breaker that truncated the measurement it protected. Both are enforced now, as a refusal that lets the batch continue rather than a trip that stops it.",
  },
  {
    t: "My opening premise was wrong for the entire build",
    d: "Every page of this project used to say a halted subscription was permanent — terminal, gone for good, no undo — and the whole recurring-revenue claim rested on it. An external reviewer challenged it on the last day. Razorpay's own documentation: “If the customer successfully changes the card details when a Subscription is in the halted state, it moves to the active state.” The premise had survived from the planning document, written before any code existed, all the way into a public README. What the documentation does support is narrower: halted stops charging automatically, the invoices it accrues are “still created. However, we will not charge these invoices. You will have to charge them manually”, and reactivation depends on a disengaged customer acting. So the claim is now five monthly collections moved off autopilot, not five customers destroyed. It is the smaller claim, and it is the one that is true.",
  },
  {
    t: "The late-revocation hazard favoured my own arm by name",
    d: "A mandate can die between the decision and the debit. That was implemented as the same hash function called on both code paths, gated on the arm's name \u2014 so it was a rule that favoured the sequencer rather than a fact both arms faced. It is now a property of the record that takes no arm argument at all, and a test parses the attempt function's syntax tree and fails if the word reappears in it. Published sensitivity: removing the hazard entirely costs 8% of the gain.",
  },
];

export default function MethodPage() {
  const { meta, llm, arms } = batch;
  const degraded = llm.llm_errors && llm.llm_errors > 0;

  return (
    <div className="mx-auto max-w-[860px] px-5 py-8 sm:px-8 sm:py-12">
      <header className="mb-10">
        <p className="eyebrow mb-3">Method</p>
        <h1 className="display text-[28px] leading-tight font-semibold sm:text-[36px]">
          What is real here, and what is not.
        </h1>
        <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">
          The bar for this track rewards honest metrics over inflated ones, so
          the limits of this measurement are stated before the results, not
          after them.
        </p>
      </header>

      <section className="mb-10 grid gap-4 sm:grid-cols-2">
        <Panel tone="mustard" title="Simulated">
          <ul className="space-y-2.5 text-[14px] leading-relaxed text-ink-soft">
            <li>
              The {meta.record_count} at-risk records, generated from seed{" "}
              {meta.seed} and reproducible.
            </li>
            <li>
              Every recovery outcome. The success probabilities are{" "}
              <strong className="font-semibold text-ink">assumptions</strong>,
              written as named constants in{" "}
              <span className="font-mono text-[12.5px]">sim/model.py</span>. They
              are not measured, not fitted, and not taken from any bank.
            </li>
          </ul>
        </Panel>
        <Panel tone="sage" title="Real">
          <ul className="space-y-2.5 text-[14px] leading-relaxed text-ink-soft">
            <li>
              Live Razorpay test-mode API calls: a real Plan, Subscription and
              Orders, logged with their IDs.
            </li>
            <li>
              The taxonomy, all seven stopping rules, both circuit breakers, the
              hash chain, and the arm comparison. None of it is mocked in the
              measurement path.
            </li>
            <li>Claude Haiku classification of free-text bank errors.</li>
          </ul>
        </Panel>
      </section>

      <section className="mb-10 rounded-2xl border border-ink/15 bg-paper-raised p-6 sm:p-8">
        <h2 className="display mb-4 text-[19px] font-semibold">
          What the numbers do and do not claim
        </h2>
        <p className="mb-4 text-[14.5px] leading-relaxed text-ink-soft">
          The absolute rupee figure is{" "}
          <strong className="font-semibold text-ink">not</strong> a claim about
          production performance. It is the output of the assumptions above.
        </p>
        <p className="border-l-2 border-ink pl-4 text-[14.5px] leading-relaxed">
          The comparison between arms{" "}
          <strong className="font-semibold">is</strong> meaningful. Both face
          identical records and identical seeded random draws, so the sequencer
          cannot win by being handed easier records, only by choosing better
          moments and by declining attempts that were never going to land. If
          the thesis were wrong, it would lose on the same draws.
        </p>
      </section>

      <section className="mb-10">
        <h2 className="display mb-1.5 text-[20px] font-semibold">
          Where a model is used, and where it is refused
        </h2>
        <p className="mb-5 text-[14px] text-ink-mute">
          A language model reads what a bank wrote and writes what a customer
          reads. It never decides whether to move money.
        </p>
        <div className="overflow-hidden rounded-2xl border border-rule bg-paper-raised">
          {AI_TABLE.map(([stage, tool, uses, why]) => (
            <div
              key={stage}
              className="grid gap-1 border-b border-rule/60 px-5 py-3.5 last:border-0 sm:grid-cols-[190px_130px_1fr] sm:items-baseline sm:gap-4"
            >
              <span className="text-[13.5px] font-medium">{stage}</span>
              <span
                className={`font-mono text-[12.5px] ${uses ? "text-ink" : "text-ink-faint"}`}
              >
                {uses ? "◆ " : "○ "}
                {tool}
              </span>
              <span className="text-[13px] leading-relaxed text-ink-mute">{why}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-10">
        <h2 className="display mb-1.5 text-[20px] font-semibold">
          This run&rsquo;s AI stage
        </h2>
        <p className="mb-4 text-[14px] text-ink-mute">
          Reported from the run that produced this page, including when it went
          wrong.
        </p>
        <div className="rounded-2xl border border-rule bg-paper-raised p-6">
          <dl className="grid gap-4 sm:grid-cols-3">
            <Metric label="Calls made" value={String(llm.llm_calls)} />
            <Metric
              label="Never reached the model"
              value={String(llm.llm_errors ?? 0)}
              tone={degraded ? "clay" : undefined}
            />
            <Metric
              label="Left unclassified → a person"
              value={String(llm.unknown)}
            />
          </dl>

          {degraded ? (
            <div className="mt-5 rounded-xl border border-mustard/40 bg-mustard-soft/35 p-4">
              <p className="mb-1.5 text-[13px] font-semibold">
                The model was unavailable for this run.
              </p>
              <p className="text-[13px] leading-relaxed text-ink-soft">
                The dictionary classified the head of the distribution as it
                always does, and every failure the dictionary could not name went
                to a person rather than to a guess. The money decisions are
                unaffected, because the breaker bounds the AI stage only. This is what
                the degradation path looks like when it runs, not a description
                of what it would do.
              </p>
              {llm.fuse_reason && (
                <p className="verdict mt-2.5">{llm.fuse_reason}</p>
              )}
            </div>
          ) : (
            <p className="mt-5 text-[13px] leading-relaxed text-ink-mute">
              Agreement with the dictionary on the sampled head:{" "}
              {llm.agree}/{llm.agree + llm.disagree}. The dictionary stays
              authoritative regardless; the sample exists to score the model, not
              to obey it.
            </p>
          )}
        </div>
      </section>

      <section className="mb-10">
        <h2 className="display mb-1.5 text-[20px] font-semibold">What broke</h2>
        <p className="mb-5 text-[14px] leading-relaxed text-ink-mute">
          Found by auditing the finished system on purpose, module by module,
          asking what happens when each part misbehaves. Three of these were
          guardrails that were themselves the hazard. All are fixed, each with a
          test that fails if the fix is reverted.
        </p>
        <ol className="space-y-3">
          {FINDINGS.map((f, i) => (
            <li
              key={f.t}
              className="rounded-2xl border border-rule bg-paper-raised p-5"
            >
              <div className="flex gap-3.5">
                <span className="tnum mt-0.5 shrink-0 font-mono text-[12px] text-ink-faint">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div>
                  <h3 className="mb-1.5 text-[14.5px] leading-snug font-semibold">
                    {f.t}
                  </h3>
                  <p className="text-[13.5px] leading-relaxed text-ink-soft">{f.d}</p>
                </div>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-5 rounded-2xl border border-ink/15 bg-paper-sunk/50 p-5 text-[14px] leading-relaxed">
          The circuit-breaker library used here,{" "}
          <a
            href="https://github.com/akshat333-debug/RunFuse"
            className="underline decoration-ink-faint underline-offset-2 hover:decoration-ink"
          >
            RunFuse
          </a>
          , is my own package on PyPI. It was tested in isolation before being
          blamed: its step limits trip precisely and its counting is exact.{" "}
          <strong className="font-semibold">
            RunFuse was correct; this project&rsquo;s containment of it was not.
          </strong>{" "}
          A dependency being right does not make your use of it safe.
        </p>
      </section>

      {/* Everything above is a defect that got fixed, which is a flattering
          shape for a list to have. These are the ones still open on submission
          day. Both are printed by `vasooli experiments` in its own output. */}
      <section className="mb-10">
        <h2 className="display mb-1.5 text-[20px] font-semibold">
          Open as of submission
        </h2>
        <ul className="space-y-1.5 text-[13.5px] leading-relaxed text-ink-mute">
          <li>
            <strong className="font-semibold text-ink-soft">
              Top-bucket calibration:
            </strong>{" "}
            predicts 0.810, observes 0.670 (n=185) — self-reported by{" "}
            <span className="font-mono text-[12.5px]">vasooli experiments</span>,
            doesn&rsquo;t affect the arm comparison.
          </li>
          <li>
            <strong className="font-semibold text-ink-soft">Rule 7:</strong>{" "}
            tested, never triggered by a seeded batch — verified logic, not
            demonstrated behaviour.
          </li>
        </ul>
      </section>

      <footer className="border-t border-rule pt-6 text-[12.5px] leading-relaxed text-ink-faint">
        <p>
          Batch generated {new Date(meta.generated_at).toLocaleString("en-IN")} ·
          seed {meta.seed} · {meta.record_count} records ·{" "}
          {arms.sequencer.attempts_spent} attempts spent by the sequencer.
        </p>
        <p className="mt-2">{meta.disclaimer}</p>
      </footer>
    </div>
  );
}

function Panel({
  tone,
  title,
  children,
}: {
  tone: "sage" | "mustard";
  title: string;
  children: React.ReactNode;
}) {
  const bg = tone === "sage" ? "bg-sage-soft/40" : "bg-mustard-soft/35";
  const dot = tone === "sage" ? "#8fae86" : "#d9ac43";
  return (
    <div className={`rounded-2xl border border-rule/70 ${bg} p-5`}>
      <div className="mb-3 flex items-center gap-2">
        <span className="h-2 w-2 rounded-full" style={{ background: dot }} />
        <h2 className="display text-[15px] font-semibold">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "clay";
}) {
  return (
    <div>
      <dd
        className="display tnum text-[26px] leading-none font-semibold"
        style={tone === "clay" ? { color: "#b5533f" } : undefined}
      >
        {value}
      </dd>
      <dt className="mt-1.5 text-[12.5px] text-ink-mute">{label}</dt>
    </div>
  );
}
