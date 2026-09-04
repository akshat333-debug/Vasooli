import raw from "../../data/batch.json";

/* Types mirror vasooli/export.py. The engine is authoritative; this file only
   describes what it emits. Nothing here recomputes a decision. */

export type Action =
  | "RETRY_SCHEDULED"
  | "HUMAN_REVIEW"
  | "STOP_EXHAUSTED"
  | "STOP_TERMINAL";

export type FailureClass =
  | "INSUFFICIENT_FUNDS"
  | "BANK_DOWNTIME"
  | "TECHNICAL_ERROR"
  | "MANDATE_REVOKED"
  | "MANDATE_EXPIRED"
  | "MANDATE_PAUSED"
  | "LIMIT_EXCEEDED"
  | "UNKNOWN";

/** The compliant next step for a record the engine declined. Mirrors
 *  decide.Escalation. A stop is not an escalation: refusing to debit is only
 *  half an answer, and the other half is where the rupee goes next. */
export type Escalation =
  | "NONE"
  | "WINBACK_CAMPAIGN"
  | "RE_MANDATE_LINK"
  | "MANDATE_UPGRADE"
  | "AFA_PAYMENT_LINK"
  | "HUMAN_REVIEW";

export interface ArmOutcome {
  recovered: boolean;
  attempts_spent: number;
  attempts_preserved: number;
  terminal_reason: string;
  rule_fired?: number;
  escalation?: Escalation;
}

export interface BatchRecord {
  subscription_id: string;
  customer_id: string;
  mandate_id: string;
  invoice_id: string;
  bank: string;
  method: string;
  amount_paise: number;
  mandate_status: string;
  mandate_max_amount_paise: number;
  mandate_valid_until: string;
  attempts_used: number;
  attempts_remaining: number;
  error_code: string;
  error_reason: string;
  error_description: string;
  last_attempt_at: string;
  pre_debit_notified_at: string | null;
  /** null when unknown -- a live webhook carries no payday. */
  salary_day: number | null;
  exceeds_mandate_cap: boolean;
  needs_human_approval: boolean;
  failure_class: FailureClass;
  diagnosis_source: string;
  diagnosis_rationale: string;
  action: Action;
  /** Which stopping rule decided this, 1-8, as reported by decide.py. */
  rule_fired: number;
  escalation: Escalation;
  escalation_label: string;
  verdict: string;
  scheduled_at: string | null;
  expected_success: number | null;
  baseline: ArmOutcome;
  sequencer: ArmOutcome;
}

export interface Arm {
  arm: string;
  run_id: string;
  records: number;
  records_processed: number;
  truncated: boolean;
  tripped: string | null;
  soft_warnings: string[];
  attempts_spent: number;
  wasted_attempts: number;
  /** Debits the money-side breaker refused at the action boundary. */
  breaker_refusals: number;
  /** Recoverable subscriptions this arm drove to `halted`. Customers lost. */
  pushed_to_halt: {
    subscription_id: string;
    amount_paise: number;
    failure_class: FailureClass;
  }[];
  value_at_risk_paise: number;
  value_recovered_paise: number;
  recovered_within_envelope_paise: number;
  recovered_above_cap_paise: number;
  /** Raw basis: includes above-cap debits. Shown for checking only. */
  paise_per_attempt: number;
  /** Compliance-adjusted basis. This is the one the headline uses. */
  adjusted_paise_per_attempt: number;
  outcomes: {
    subscription_id: string;
    amount_paise: number;
    failure_class: FailureClass;
    recovered: boolean;
    attempts_spent: number;
    attempts_preserved: number;
    terminal_reason: string;
  }[];
}

export interface LedgerEntry {
  /** The hashed body, exported so the chain can be recomputed in the browser
   *  rather than merely asserted. See lib/verifyChain.ts. */
  payload?: Record<string, unknown>;
  idx: number;
  ts: string;
  run_id: string;
  arm: string;
  subscription_id: string | null;
  event: string;
  verdict: string;
  hash: string;
  prev_hash: string;
}

export interface Scenario {
  id: string;
  name: string;
  note: string;
  disabled_rules: number[];
  attempts_spent: number;
  wasted_attempts: number;
  breaker_refusals: number;
  recovered_within_envelope_paise: number;
  recovered_above_cap_paise: number;
  adjusted_paise_per_attempt: number;
  records_processed: number;
  truncated: boolean;
  tripped: string | null;
}

export interface Batch {
  meta: {
    generated_at: string;
    batch_reference_time: string;
    seed: number;
    record_count: number;
    retry_budget_per_record: number;
    synthetic: boolean;
    disclaimer: string;
  };
  arms: { baseline: Arm; sequencer: Arm };
  escalation_labels: Record<string, string>;
  records: BatchRecord[];
  scenarios: Scenario[];
  ledger: {
    verified: boolean;
    keyed?: boolean;
    strength?: string;
    rows: number;
    broken_at: number | null;
    detail: string;
    entries: LedgerEntry[];
  };
  llm: {
    llm_calls: number;
    agree: number;
    disagree: number;
    llm_rescued: number;
    unknown: number;
    llm_errors?: number;
    degraded?: number;
    degraded_reason?: string;
    fuse_aborted?: number;
    fuse_reason?: string;
  };
}

export const batch = raw as unknown as Batch;

/* ---- formatting ---------------------------------------------------------- */

/** Rupees, grouped Indian-style. Money is always shown whole — no abbreviations
 *  like "₹71.9k", because a reader checking an audit trail needs the figure. */
export function rupees(paise: number, opts: { decimals?: boolean } = {}) {
  const v = paise / 100;
  return (
    "₹" +
    v.toLocaleString("en-IN", {
      minimumFractionDigits: opts.decimals ? 2 : 0,
      maximumFractionDigits: opts.decimals ? 2 : 0,
    })
  );
}

export const ACTION_LABEL: Record<Action, string> = {
  RETRY_SCHEDULED: "Retry scheduled",
  HUMAN_REVIEW: "Sent to a person",
  STOP_EXHAUSTED: "Budget already spent",
  STOP_TERMINAL: "Refused",
};

/** Which semantic colour an action carries. See globals.css for the contract. */
export const ACTION_TONE: Record<Action, "sage" | "periwinkle" | "mustard"> = {
  RETRY_SCHEDULED: "sage",
  HUMAN_REVIEW: "mustard",
  STOP_EXHAUSTED: "periwinkle",
  STOP_TERMINAL: "periwinkle",
};

export const TONE_HEX: Record<string, string> = {
  sage: "#8fae86",
  periwinkle: "#8f8fe8",
  mustard: "#d9ac43",
  clay: "#b5533f",
};

export function classLabel(c: FailureClass) {
  return c.toLowerCase().replace(/_/g, " ");
}
