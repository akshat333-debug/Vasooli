"""The bandit is an experiment, not a component. These tests pin that.

The most important assertions here are the ones that stop it quietly becoming
load-bearing, and the one that stops the evaluation from flattering it.
"""

from vasooli.bandit import (
    ARMS_HOURS,
    PERTURBATION,
    ThompsonBandit,
    context_of,
    observations_per_context,
    train,
)
from vasooli.sim import model
from vasooli.sim.seed import BATCH_NOW, generate_batch
from vasooli.taxonomy import FailureClass


def test_it_is_not_wired_into_the_decision_path():
    # A sampled policy in a money path breaks the reproducibility argument the
    # whole project rests on. If someone imports this from decide.py or
    # execute.py, this fails and they have to argue for it.
    import inspect

    from vasooli import decide, execute
    for mod in (decide, execute):
        assert "bandit" not in inspect.getsource(mod), (
            f"{mod.__name__} imports the bandit — a sampled policy is now "
            f"deciding when to move money"
        )


def test_context_is_small_enough_to_learn():
    # 8 banks in the context produced 1,055 cells with a median of ONE
    # observation each. Any context wide enough to do that again is unusable.
    # Uses the same seed count as the real study. Testing power at 5 seeds
    # would measure the test's own sample size, not the context design.
    b = train(ThompsonBandit(), list(range(1, 41)))
    power = observations_per_context(b)
    assert power["median_obs_per_cell"] >= 5, (
        f"median {power['median_obs_per_cell']} observations per cell — "
        f"a posterior built on that is noise"
    )
    assert power["share_underpowered"] < 0.5, (
        f"{power['share_underpowered']:.0%} of cells have under five "
        f"observations; the context is still too wide"
    )


def test_context_excludes_the_bank():
    rec = generate_batch(1, seed=42)[0]
    ctx = context_of(rec, FailureClass.INSUFFICIENT_FUNDS, BATCH_NOW)
    assert rec.bank not in ctx


def test_posterior_updates_in_the_right_direction():
    b = ThompsonBandit()
    ctx = ("INSUFFICIENT_FUNDS", "fresh", 0)
    for _ in range(20):
        b.update(ctx, ARMS_HOURS[0], True)
    for _ in range(20):
        b.update(ctx, ARMS_HOURS[1], False)
    assert b.best(ctx) == ARMS_HOURS[0]


def test_greedy_choice_is_deterministic():
    # Evaluation must not itself be a coin flip.
    b = train(ThompsonBandit(), [1, 2])
    ctx = ("INSUFFICIENT_FUNDS", "fresh", 0)
    assert len({b.best(ctx) for _ in range(50)}) == 1


def test_training_is_reproducible():
    a = train(ThompsonBandit(), [1, 2, 3]).posterior
    c = train(ThompsonBandit(), [1, 2, 3]).posterior
    assert a == c


def test_perturbation_is_restored_after_a_study(monkeypatch):
    # A study that leaks a shifted assumption into the live model would corrupt
    # every number produced afterwards in the same process.
    from vasooli.bandit import shift_sweep
    before = {k: getattr(model, k) for k in PERTURBATION}
    shift_sweep(train_seeds=[1, 2], test_seeds=[200], n=30, steps=2)
    assert {k: getattr(model, k) for k in PERTURBATION} == before


def test_perturbation_actually_changes_the_world():
    # If the "shifted" world were identical to the assumed one, the
    # out-of-distribution number would be in-distribution wearing a label.
    for k, v in PERTURBATION.items():
        assert getattr(model, k) != v, f"{k} perturbation is a no-op"
