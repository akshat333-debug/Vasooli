"""Money-side circuit breaker.

RunFuse guards the AI side of this system — spend, steps, retry storms against
the model. It does not guard rupees, and pretending otherwise would be exactly
the kind of overclaim this project is supposed to be the opposite of.

So the money side gets its own breaker, deliberately built on RunFuse's
semantics because those semantics are right:

  * hard limits that raise rather than warn
  * a human-readable verdict string on every trip, not a bare error
  * a soft threshold that fires a warning before the hard stop
  * trips checked at the ACTION BOUNDARY, never mid-action

That last one is not a stylistic echo. RunFuse trips at LLM call boundaries
rather than mid-tool for a specific reason: a limit checked at the wrong moment
lets state change underneath the decision. The identical problem exists here —
a mandate can be revoked between the moment we decide to retry and the moment we
retry — which is why execute.py re-checks at the boundary instead of trusting
the decision it was handed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import MAX_RETRY_BUDGET, RBI_STANDARD_CAP_PAISE


class RecoveryTripped(Exception):
    """A batch-level limit was breached. Carries the verdict and the state."""

    def __init__(self, verdict: str, state: RecoveryState) -> None:
        super().__init__(verdict)
        self.verdict = verdict
        self.state = state


class ActionRefused(Exception):
    """One debit was refused at the boundary. The batch continues.

    Distinct from RecoveryTripped, which halts the whole run. A PER-DEBIT limit
    that tripped the batch would truncate the measurement it is supposed to
    protect — that was defect 2, where a batch ceiling cut the comparison off at
    60 actions and the report presented the prefix as a result.

    So: per-debit limits refuse the action and record why; aggregate limits trip.
    """

    def __init__(self, verdict: str, state: RecoveryState) -> None:
        super().__init__(verdict)
        self.verdict = verdict
        self.state = state


@dataclass(frozen=True)
class RecoveryPolicy:
    """Hard limits on what automation may do with money, unsupervised."""

    #: Razorpay halts a subscription once its retries are spent. Never exceed.
    max_attempts_per_subscription: int = MAX_RETRY_BUDGET

    #: RBI e-mandate standard cap. Above this, a human approves the debit.
    max_auto_amount_paise: int = RBI_STANDARD_CAP_PAISE

    #: Ceiling on how many debits one unattended batch may attempt.
    #: Sized above a 100-record batch's worst case (3 attempts each) so that the
    #: arm comparison runs to completion. A ceiling that truncates the batch
    #: would confound the measurement rather than protect anything — the trip is
    #: demonstrated deliberately via `vasooli demo-trip` instead.
    max_actions_per_batch: int = 300

    #: Ceiling on total value one unattended batch may attempt to move.
    max_total_auto_value_paise: int = 5_00_000_00

    #: Fraction of a limit at which a warning fires but the run continues.
    soft_threshold: float = 0.8

    name: str = "vasooli-recovery"


@dataclass
class RecoveryState:
    """Live counters for one batch run."""

    actions_taken: int = 0
    value_attempted_paise: int = 0
    value_recovered_paise: int = 0
    refusals: int = 0
    soft_warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {
            "actions_taken": self.actions_taken,
            "value_attempted_paise": self.value_attempted_paise,
            "value_recovered_paise": self.value_recovered_paise,
            "refusals": self.refusals,
        }


class RecoveryFuse:
    """Batch-level breaker. Checked before every money action, never during."""

    def __init__(self, policy: RecoveryPolicy | None = None) -> None:
        self.policy = policy or RecoveryPolicy()
        self.state = RecoveryState()

    def check(self, amount_paise: int, *, attempts_on_subscription: int = 0) -> None:
        """Assert the batch may attempt one more debit of this size.

        Raises ActionRefused for a per-debit limit (this action is refused, the
        batch continues) and RecoveryTripped for an aggregate ceiling (the run
        stops). Called at the action boundary in execute.py.
        """
        p, s = self.policy, self.state

        # A non-positive debit is not a real action, and letting one through
        # would *reduce* the batch's attempted total — quietly raising the
        # ceiling for every action after it. Cheap guard at a money boundary.
        if amount_paise <= 0:
            raise RecoveryTripped(
                f"invalid_amount: {amount_paise} paise — a debit must be a "
                "positive amount; refusing to account it against the batch",
                s,
            )

        # PER-DEBIT LIMITS. Both of these were declared on RecoveryPolicy with
        # comments asserting they were limits, and enforced by nothing (defect
        # 18) — the same shape as RunFuse's inert cost cap. A limit that does not
        # trip is decoration.
        if amount_paise > p.max_auto_amount_paise:
            s.refusals += 1
            raise ActionRefused(
                f"refused: ₹{amount_paise / 100:,.2f} exceeds the unattended cap "
                f"₹{p.max_auto_amount_paise / 100:,.2f} — this debit needs AFA and "
                "will not be presented unattended",
                s,
            )

        if attempts_on_subscription + 1 > p.max_attempts_per_subscription:
            s.refusals += 1
            raise ActionRefused(
                f"refused: attempt {attempts_on_subscription + 1} would exceed the "
                f"{p.max_attempts_per_subscription}-attempt budget on this "
                "subscription — a further attempt halts it",
                s,
            )

        # AGGREGATE LIMITS. These stop the run.
        if s.actions_taken + 1 > p.max_actions_per_batch:
            raise RecoveryTripped(
                f"max_actions_per_batch: {s.actions_taken + 1} > {p.max_actions_per_batch} "
                "— unattended batch action ceiling reached",
                s,
            )

        projected = s.value_attempted_paise + amount_paise
        if projected > p.max_total_auto_value_paise:
            raise RecoveryTripped(
                f"max_total_auto_value_paise: ₹{projected / 100:,.2f} > "
                f"₹{p.max_total_auto_value_paise / 100:,.2f} "
                "— unattended batch value ceiling reached",
                s,
            )

        self._soft(s.actions_taken + 1, p.max_actions_per_batch, "actions")
        self._soft(projected, p.max_total_auto_value_paise, "value")

    def _soft(self, current: float, limit: float, label: str) -> None:
        """Warn once per limit, on first crossing — not once per step.

        A warning that repeats every action is noise, and noise is how a real
        warning gets missed.
        """
        if not limit or current < limit * self.policy.soft_threshold:
            return
        if any(w.startswith(f"soft: {label} ") for w in self.state.soft_warnings):
            return
        self.state.soft_warnings.append(
            f"soft: {label} crossed {self.policy.soft_threshold:.0%} of its limit "
            f"({current / limit:.0%}) — approaching the unattended ceiling"
        )

    def record(self, *, amount_paise: int, recovered: bool) -> None:
        self.state.actions_taken += 1
        self.state.value_attempted_paise += amount_paise
        if recovered:
            self.state.value_recovered_paise += amount_paise
