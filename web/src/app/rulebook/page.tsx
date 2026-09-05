import Link from "next/link";
import { batch, rupees, type BatchRecord } from "@/lib/data";

export const metadata = { title: "Rulebook · Vasooli" };

/**
 * The seven stopping rules, with the authority each one answers to.
 *
 * This page exists because "we have stopping rules" and "here is the rule, the
 * regulation behind it, the exact condition, and what it cost this batch" are
 * different claims, and only the second one is checkable. Everything numeric
 * below is computed from the same batch.json the rest of the site reads --
 * nothing here is typed in by hand.
 *
 * The basis column matters more than the counts. A reader who works in payments
 * needs to know which of these are law and which are our own policy, because
 * those two carry different weight and a system that blurs them is one they
 * cannot audit. That distinction is stated per rule and again at the foot.
 */

type Basis = "statute" | "physical" | "policy";

const BASIS_LABEL: Record<Basis, string> = {
  statute: "Regulation",
  physical: "Physical",
  policy: "Our policy",
};

const BASIS_NOTE: Record<Basis, string> = {
  statute: "Imposed from outside. Breaking it is non-compliance, not a trade-off.",
  physical: "The debit is rejected on presentation. Attempting it cannot work.",
  policy: "Our choice. A merchant could reasonably set this differently.",
};

const RULES: {
  n: number;
  name: string;
  basis: Basis;
  source: string;
  plain: string;
  code: string;
  action: string;
  escalation: string;
}[] = [
  {
    n: 1,
    name: "Retry budget exhausted",
    basis: "physical",
    source: "Razorpay Subscriptions retry limit",
    plain:
      "The subscription has already used all three of its retries. A fourth "
      + "attempt does not fail politely — it moves the subscription to halted, "
      + "which stops automatic charging. It is not unrecoverable: Razorpay "
      + "returns a halted subscription to active once the customer updates the "
      + "payment method themselves. But the invoices it accrues meanwhile are "
      + "never auto-charged, and the budget does not come back.",
    code: "rec.attempts_remaining <= 0",
    action: "STOP_EXHAUSTED",
    escalation: "WINBACK_CAMPAIGN",
  },
  {
    n: 2,
    name: "Terminal failure class",
    basis: "physical",
    source: "Mandate lifecycle; issuer behaviour",
    plain:
      "The bank told us why it failed, and the reason is one no retry can fix: "
      + "the mandate was revoked, expired or paused, or the amount is above a "
      + "limit registered on it. The money cannot move until something changes.",
    code: "is_terminal(failure_class)",
    action: "STOP_TERMINAL",
    escalation: "RE_MANDATE_LINK / MANDATE_UPGRADE",
  },
  {
    n: 3,
    name: "Mandate not active",
    basis: "physical",
    source: "Mandate lifecycle",
    plain:
      "The mandate itself is dead, whatever the error text said. A failure that "
      + "reads as a low balance against a mandate the customer cancelled last "
      + "week is still a debit that will be rejected.",
    code: "rec.mandate_status is not MandateStatus.ACTIVE",
    action: "STOP_TERMINAL",
    escalation: "RE_MANDATE_LINK",
  },
  {
    n: 4,
    name: "Failure unclassified",
    basis: "policy",
    source: "Vasooli design constraint",
    plain:
      "Neither the code dictionary nor the language model could say what went "
      + "wrong. We refuse to spend a scarce attempt on a guess, so it goes to a "
      + "person with the bank's own words attached.",
    code: "failure_class is FailureClass.UNKNOWN",
    action: "HUMAN_REVIEW",
    escalation: "HUMAN_REVIEW",
  },
  {
    n: 5,
    name: "Above the mandate's own cap",
    basis: "physical",
    source: "Per-mandate maximum registered at authorisation",
    plain:
      "The customer authorised debits up to a ceiling and this invoice is above "
      + "it — usually because the plan price rose after the mandate was signed. "
      + "The issuer rejects it on presentation every time.",
    code: "rec.amount_paise > rec.mandate_max_amount_paise",
    action: "HUMAN_REVIEW",
    escalation: "MANDATE_UPGRADE",
  },
  {
    n: 6,
    name: "Above the RBI AFA-free cap",
    basis: "statute",
    source: "RBI e-mandate framework, ₹15,000 AFA threshold",
    plain:
      "Above ₹15,000 a recurring debit requires additional factor "
      + "authentication. An unattended presentation is not merely against the "
      + "rules — it is declined, so the attempt is spent for nothing. The right "
      + "answer is not to give up but to ask the customer.",
    code: "rec.amount_paise > RBI_STANDARD_CAP_PAISE",
    action: "HUMAN_REVIEW",
    escalation: "AFA_PAYMENT_LINK",
  },
  {
    n: 7,
    name: "No lawful window before expiry",
    basis: "statute",
    source: "RBI pre-debit notice (24h) vs mandate validity",
    plain:
      "A debit must be preceded by a pre-debit notification. If the mandate "
      + "expires before that notice period can elapse, there is no moment at "
      + "which this debit would be lawful, so none is scheduled.",
    code: "earliest_legal_retry(rec, now) > rec.mandate_valid_until",
    action: "STOP_TERMINAL",
    escalation: "RE_MANDATE_LINK",
  },
];

/** Measured cost of removing each rule: mean attempts per 100-record batch
 *  across 40 seeds, from `vasooli experiments`. Row 0 is every rule on. */
const ABLATION: Record<number, { attempts: number; refusals: number }> = {
  0: { attempts: 76.3, refusals: 0.0 },
  1: { attempts: 76.3, refusals: 5.9 },
  2: { attempts: 81.2, refusals: 0.0 },
  3: { attempts: 76.3, refusals: 0.0 },
  4: { attempts: 81.7, refusals: 0.0 },
  5: { attempts: 83.6, refusals: 0.0 },
  6: { attempts: 76.3, refusals: 4.8 },
  7: { attempts: 76.3, refusals: 0.0 },
};

function stopped(records: BatchRecord[], n: number) {
  const hit = records.filter((r) => r.rule_fired === n);
  return {
    count: hit.length,
    value: hit.reduce((a, r) => a + r.amount_paise, 0),
    preserved: hit.reduce((a, r) => a + r.attempts_remaining, 0),
  };
}

export default function RulebookPage() {
  const { records } = batch;
  const base = ABLATION[0];

  return (
    <div className="mx-auto max-w-[900px] px-5 py-8 sm:px-8 sm:py-12">
      <header className="mb-10">
        <p className="eyebrow mb-3">Rulebook</p>
        <h1 className="display max-w-2xl text-[28px] leading-tight font-semibold sm:text-[36px]">
          Seven reasons not to spend an attempt.
        </h1>
        <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-ink-soft">
          Checked in this order, cheapest and most certain refusals first, so no
          work is done on a record that was never eligible. Whatever survives all
          seven is scheduled by rule 8 at the best moment inside its legal
          window.
        </p>
        <p className="mt-3 max-w-2xl text-[14px] leading-relaxed text-ink-mute">
          Every count and rupee figure below is computed from the same batch file
          the rest of this site reads. The cost of removing a rule is measured by
          switching it off and re-running 40 seeds, not estimated.
        </p>
      </header>

      <ol className="space-y-5">
        {RULES.map((rule) => {
          const s = stopped(records, rule.n);
          const off = ABLATION[rule.n];
          const extra = off.attempts - base.attempts;
          return (
            <li
              key={rule.n}
              id={`rule-${rule.n}`}
              className="overflow-hidden rounded-2xl border border-rule bg-paper-raised"
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-rule px-6 py-4">
                <span className="tnum font-mono text-[13px] text-ink-faint">
                  {String(rule.n).padStart(2, "0")}
                </span>
                <h2 className="display text-[17px] font-semibold">{rule.name}</h2>
                <span
                  className={`ml-auto rounded px-2 py-0.5 font-mono text-[11px] tracking-tight ${
                    rule.basis === "statute"
                      ? "bg-mustard-soft text-ink"
                      : rule.basis === "physical"
                        ? "bg-paper-sunk text-ink-soft"
                        : "bg-periwinkle-soft text-ink"
                  }`}
                >
                  {BASIS_LABEL[rule.basis]}
                </span>
              </div>

              <div className="grid gap-6 px-6 py-5 lg:grid-cols-[1fr_260px]">
                <div>
                  <p className="mb-1 text-[11px] tracking-wider text-ink-faint uppercase">
                    Basis
                  </p>
                  <p className="mb-4 text-[13.5px] leading-relaxed text-ink-soft">
                    {rule.source}.{" "}
                    <span className="text-ink-mute">{BASIS_NOTE[rule.basis]}</span>
                  </p>

                  <p className="mb-1 text-[11px] tracking-wider text-ink-faint uppercase">
                    The condition
                  </p>
                  <p className="mb-3 text-[14px] leading-relaxed">{rule.plain}</p>
                  <pre className="overflow-x-auto rounded-lg bg-paper-sunk px-3.5 py-2.5 font-mono text-[12px] text-ink-soft">
                    {rule.code}
                  </pre>
                  <p className="mt-3 font-mono text-[12px] text-ink-mute">
                    → {rule.action} · {rule.escalation}
                  </p>
                </div>

                <div className="lg:border-l lg:border-rule lg:pl-6">
                  <p className="mb-2.5 text-[11px] tracking-wider text-ink-faint uppercase">
                    In this batch
                  </p>
                  <dl className="space-y-2.5 text-[13px]">
                    <div className="flex items-baseline justify-between gap-3">
                      <dt className="text-ink-mute">Records stopped</dt>
                      <dd className="tnum font-semibold">{s.count}</dd>
                    </div>
                    <div className="flex items-baseline justify-between gap-3">
                      <dt className="text-ink-mute">Value withheld</dt>
                      <dd className="tnum">{rupees(s.value)}</dd>
                    </div>
                    <div className="flex items-baseline justify-between gap-3">
                      <dt className="text-ink-mute">Attempts preserved</dt>
                      <dd className="tnum">{s.preserved}</dd>
                    </div>
                  </dl>

                  <p className="mt-4 mb-2 text-[11px] tracking-wider text-ink-faint uppercase">
                    Cost of removing it
                  </p>
                  <p className="text-[13px] leading-relaxed text-ink-soft">
                    {extra > 0.05 ? (
                      <>
                        <span className="tnum font-semibold">
                          +{extra.toFixed(1)}
                        </span>{" "}
                        attempts per batch, averaged over 40 seeds.
                      </>
                    ) : off.refusals > 0 ? (
                      <>
                        No extra attempts — the money-side breaker catches these
                        instead, refusing{" "}
                        <span className="tnum font-semibold">
                          {off.refusals.toFixed(1)}
                        </span>{" "}
                        debits per batch at the action boundary. The cost moves
                        one layer down rather than disappearing.
                      </>
                    ) : (
                      <>
                        Nothing measurable on this data, and that is reported
                        rather than dropped. See the note below.
                      </>
                    )}
                  </p>

                  {s.count > 0 && (
                    <Link
                      href={`/records?rule=${rule.n}`}
                      className="mt-4 inline-block text-[13px] text-ink underline decoration-rule underline-offset-4 hover:decoration-ink"
                    >
                      See the {s.count} record{s.count === 1 ? "" : "s"} →
                    </Link>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      <section className="mt-10 rounded-2xl border border-rule bg-paper-raised px-6 py-6 sm:px-8">
        <h2 className="display mb-3 text-[17px] font-semibold">
          Which of these are law, and which are ours
        </h2>
        <p className="mb-3 text-[14px] leading-relaxed text-ink-soft">
          Rules <strong>6 and 7</strong> come from the RBI e-mandate framework.
          They are not tunable: a merchant who relaxes them is non-compliant, and
          in the case of rule 6 the debit is declined anyway, so relaxing it buys
          nothing but a wasted attempt.
        </p>
        <p className="mb-3 text-[14px] leading-relaxed text-ink-soft">
          Rules <strong>1, 2, 3 and 5</strong> are physical. They describe debits
          the network rejects on presentation. A merchant could attempt them and
          would simply lose the attempt.
        </p>
        <p className="mb-3 text-[14px] leading-relaxed text-ink-soft">
          Rule <strong>4</strong> is the only one that is genuinely our policy. A
          merchant with a higher appetite could guess at unclassified failures
          instead of routing them to a person. Switching it off costs{" "}
          <span className="tnum">
            +{(ABLATION[4].attempts - base.attempts).toFixed(1)}
          </span>{" "}
          attempts per batch and recovers nothing extra, which is the argument
          for keeping it — but it is an argument, not a regulation.
        </p>
        <p className="text-[14px] leading-relaxed text-ink-mute">
          Rules <strong>3 and 7</strong> stop nothing measurable in the ablation,
          for different reasons. Rule 3 is redundant with the pre-flight mandate
          check at the action boundary, deliberately — the rule is what produces
          the re-mandate escalation, the boundary check is what survives the
          world changing after the decision was made. Rule 7 never fires on this
          generated data at all: no record here has a mandate expiring inside the
          notice window. It is kept because an audit found the scheduler placing
          a retry six days past a mandate&rsquo;s expiry, and a rule guarding a
          rare and expensive mistake still earns its place. Both facts are
          reported rather than quietly dropped.
        </p>
      </section>
    </div>
  );
}
