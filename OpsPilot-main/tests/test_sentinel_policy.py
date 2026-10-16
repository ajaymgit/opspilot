"""Unit tests for SentinelPolicy: adaptive guardrail thresholds (Idea 2 / G9)."""

from pathlib import Path

import pytest

from opspilot.governance.guardrail_rules import get_all_prohibited_rules
from opspilot.governance.sentinel_policy.policy_agent import (
    DEFAULT_ARMS, ESCALATION_MARGIN, GuardrailPolicyAgent, ModuleContext, check_hard_constraints,
)
from opspilot.governance.sentinel_policy.risk_scoring import RISK_CATEGORIES, score_soft_risks
from opspilot.governance.sentinel_policy.synthetic_reviewer import SyntheticReviewer
from opspilot.governance.sentinel_policy.thompson_bandit import ThompsonThresholdBandit


# ---------------------------------------------------------------------------
# Hard-constraint backstop: must never be bypassable via the adaptive layer.
# ---------------------------------------------------------------------------

def test_hard_constraints_reuse_canonical_denylist():
    """SentinelPolicy must check against the SAME rule set as the base pipeline
    guardrail interceptor, never a forked copy that could drift out of sync."""
    canonical_ids = {r["id"] for r in get_all_prohibited_rules()}
    assert "RULE_SYSTEM_EXIT" in canonical_ids
    assert check_hard_constraints("System.exit(1);")["rule_id"] == "RULE_SYSTEM_EXIT"
    assert check_hard_constraints("public class Clean { void run() {} }") is None


def test_hard_violation_short_circuits_before_soft_layer(tmp_path):
    """A hard-constraint violation must never reach the bandit-governed layer,
    regardless of how the adaptive thresholds are currently calibrated."""
    agent = GuardrailPolicyAgent(seed=1)
    decision = agent.evaluate("Runtime.getRuntime().exec(\"rm -rf /\");", ModuleContext(module_id="m1"))
    assert decision.overall_decision == "HARD_VIOLATION"
    assert decision.category_decisions == []
    # nothing was queued for bandit feedback
    assert decision.decision_id not in agent._pending


def test_hard_constraint_never_learnable():
    """Confirms there is no code path by which recording a human disposition
    could touch the hard-constraint layer -- it is not bandit-managed state."""
    agent = GuardrailPolicyAgent(seed=1)
    decision = agent.evaluate("DROP TABLE accounts;", ModuleContext(module_id="m2"))
    assert decision.overall_decision == "HARD_VIOLATION"
    # recording a disposition against a hard-violation decision_id is a no-op
    agent.record_human_disposition(decision.decision_id, {"FINANCIAL_PRECISION": True})
    # bandit state for every category remains at its untouched prior
    for cat_id in RISK_CATEGORIES:
        for arm in DEFAULT_ARMS:
            beta_arm = agent.bandit._group(cat_id, "STANDARD")[arm]
            assert beta_arm.alpha == 1.0 and beta_arm.beta == 1.0


# ---------------------------------------------------------------------------
# Soft risk scoring
# ---------------------------------------------------------------------------

def test_clean_code_scores_zero_everywhere():
    clean = "package x;\npublic class Clean {\n    public void run() { int a = 1; }\n}\n"
    scores = score_soft_risks(clean, "STANDARD")
    assert all(s == 0.0 for s in scores.values())


def test_financial_precision_pattern_detected():
    risky = "double totalPayAmount = grossPay - taxDue;\n" * 5
    scores = score_soft_risks(risky, "FINANCIAL")
    assert scores["FINANCIAL_PRECISION"] > 0.0


def test_severity_weighting_differs_by_module_class():
    """The same code should score as riskier on a FINANCIAL module than on a
    UTILITY module for the financial-precision category, per the survey's
    'strict for payment logic, permissive for utility modules' framing."""
    risky = "double totalPayAmount = grossPay - taxDue;\n" * 3
    financial_score = score_soft_risks(risky, "FINANCIAL")["FINANCIAL_PRECISION"]
    utility_score = score_soft_risks(risky, "UTILITY")["FINANCIAL_PRECISION"]
    assert financial_score > utility_score


def test_all_category_snippets_actually_trigger_their_own_pattern():
    """Regression guard for the DEPRECATED_API snippet/regex mismatch bug found
    during evaluation-harness development: every synthetic snippet used to
    generate evaluation data must actually match the category it's meant to
    represent, or the evaluation silently measures the wrong thing."""
    from opspilot.governance.sentinel_policy.synthetic_module_generator import CATEGORY_SNIPPETS
    for cat_id, category in RISK_CATEGORIES.items():
        snippet = CATEGORY_SNIPPETS[cat_id]
        assert any(p.search(snippet) for p in category.patterns), (
            f"Synthetic snippet for {cat_id} does not match its own detection pattern"
        )


# ---------------------------------------------------------------------------
# GuardrailPolicyAgent decision semantics
# ---------------------------------------------------------------------------

def test_decision_semantics_approve_reject_escalate():
    """With a single fixed arm, verify the score-vs-threshold decision boundary
    (comfortably under -> APPROVE, comfortably over -> REJECT, near -> ESCALATE)."""
    bandit = ThompsonThresholdBandit(arms=[0.5], seed=1)
    agent = GuardrailPolicyAgent(bandit=bandit)

    # force the bandit to always return the single arm 0.5 regardless of sampling
    assert agent.bandit.select_arm("FINANCIAL_PRECISION", "STANDARD") == 0.5

    clean_module = ModuleContext(module_id="clean")
    decision = agent.evaluate("public class Clean { public void run() { int a=1; } }", clean_module)
    assert decision.overall_decision == "APPROVE"

    risky_module = ModuleContext(module_id="risky", risk_class="FINANCIAL")
    risky_code = "double totalPayAmount = grossPay - taxDue;\n" * 8
    decision = agent.evaluate(risky_code, risky_module)
    assert decision.overall_decision in ("REJECT", "ESCALATE")


def test_default_arms_never_flag_a_clean_module_regardless_of_arm():
    """Regression guard: the smallest threshold arm must stay comfortably above
    ESCALATION_MARGIN so a module with zero risk score in every category is
    always approvable no matter which arm is currently selected. (An earlier
    version of the threshold ladder had its lowest arm equal to the margin,
    which meant even entirely clean code was always escalated.)"""
    assert min(DEFAULT_ARMS) - ESCALATION_MARGIN > 0.0


def test_clean_module_always_approved_across_all_arms():
    clean_code = "package x;\npublic class Clean {\n    public void run() { int a = 1; }\n}\n"
    for risk_class in ("FINANCIAL", "UTILITY", "STANDARD"):
        scores = score_soft_risks(clean_code, risk_class)
        for arm in DEFAULT_ARMS:
            for score in scores.values():
                assert score < arm - ESCALATION_MARGIN


# ---------------------------------------------------------------------------
# Bandit learning: per-category reward isolation (regression test for the bug
# where an aggregate module-level AND was recorded against every category).
# ---------------------------------------------------------------------------

def test_reward_isolated_per_category_not_aggregated():
    """A disagreement on one category must not suppress the reward for another,
    unrelated category in the same decision."""
    bandit = ThompsonThresholdBandit(arms=[0.2, 0.8], seed=1)
    agent = GuardrailPolicyAgent(bandit=bandit)

    # construct code that triggers exactly one soft category (financial precision)
    code = "double totalPayAmount = grossPay - taxDue;\n" * 6
    ctx = ModuleContext(module_id="m", risk_class="FINANCIAL")
    decision = agent.evaluate(code, ctx)
    assert any(c.category == "FINANCIAL_PRECISION" and c.decision != "APPROVE" for c in decision.category_decisions)

    # human disagrees on FINANCIAL_PRECISION (overrides to approve) but the
    # dispositions dict simply omits every other category (as evaluate.py
    # would for categories a real reviewer never even looked at)
    agent.record_human_disposition(decision.decision_id, {"FINANCIAL_PRECISION": True})

    triggered = next(c for c in decision.category_decisions if c.category == "FINANCIAL_PRECISION")
    beta_arm = agent.bandit._group("FINANCIAL_PRECISION", "FINANCIAL")[triggered.threshold]
    # policy flagged it (not APPROVE), human approved -> disagreement -> failure recorded
    assert beta_arm.beta == 2.0
    assert beta_arm.alpha == 1.0

    # a category that was never mentioned in the disposition dict must be untouched
    for cat_id in RISK_CATEGORIES:
        if cat_id == "FINANCIAL_PRECISION":
            continue
        for arm in bandit.arms:
            b = agent.bandit._group(cat_id, "FINANCIAL")[arm]
            assert b.alpha == 1.0 and b.beta == 1.0


def test_bandit_learns_permissive_threshold_for_high_override_category():
    """Sanity-checks the learning mechanism end to end: for a category the
    SyntheticReviewer almost always overrides on a non-financial module, the
    bandit should converge toward a more permissive (higher) threshold than for
    a category that is rarely overridden."""
    from opspilot.governance.sentinel_policy.synthetic_module_generator import generate_module_stream

    modules = generate_module_stream(n_modules=1500, seed=7)
    reviewer = SyntheticReviewer(seed=8)
    agent = GuardrailPolicyAgent(seed=7)

    for mod in modules:
        ctx = ModuleContext(module_id=mod.module_id, risk_class=mod.risk_class, complexity=0.5)
        decision = agent.evaluate(mod.code_text, ctx)
        if decision.overall_decision == "HARD_VIOLATION":
            continue
        per_cat = {c.category: reviewer.disposition(c.category, c.decision, ctx.risk_class)
                   for c in decision.category_decisions}
        agent.record_human_disposition(decision.decision_id, per_cat)

    # DEPRECATED_API has a high override probability (0.55) on UTILITY modules;
    # FINANCIAL_PRECISION has a very low one (0.05, further dampened) on
    # FINANCIAL modules. The learned threshold for the high-override category
    # should end up more permissive (higher) than for the low-override one.
    permissive_threshold = agent.bandit.best_arm_by_posterior_mean("DEPRECATED_API", "UTILITY")
    strict_threshold = agent.bandit.best_arm_by_posterior_mean("FINANCIAL_PRECISION", "FINANCIAL")
    assert permissive_threshold > strict_threshold


# ---------------------------------------------------------------------------
# Evaluation harness sanity checks (small-scale, fast)
# ---------------------------------------------------------------------------

def test_evaluation_harness_runs_and_preserves_hard_constraint_catch_rate(tmp_path):
    from opspilot.governance.sentinel_policy.evaluate import run_evaluation

    summary, training_windows, static_windows, adaptive_windows = run_evaluation(
        n_train=300, n_holdout=150, window=50, output_dir=Path(tmp_path)
    )
    assert summary["static_hard_violation_catch_rate"] == 1.0
    assert summary["adaptive_hard_violation_catch_rate"] == 1.0
    assert (Path(tmp_path) / "summary.json").exists()
