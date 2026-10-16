"""Evaluation harness for SentinelPolicy.

Experimental design
--------------------
A single online run that both learns and is scored on the same stream conflates
two different signals: the bandit's own exploration noise, and whatever genuine
calibration improvement it is making. With a 10-dimensional context, a handful of
threshold arms, and a category-level "reward" that is inherently stochastic
(the SyntheticReviewer's override decision is a coin flip, not a deterministic
function of score), a live windowed curve over one continuous run is dominated by
sampling noise at any window size small enough to still show trend within a few
thousand modules -- exactly the kind of confound a careful evaluation should
avoid conflating with a genuine effect.

So this harness uses a train/freeze/holdout split, standard ML-evaluation
practice:

  1. TRAIN phase: SentinelPolicy's bandit learns online over `n_train`
     synthetic modules (with active UCB exploration).
  2. FREEZE: exploration is turned off (alpha -> ~0) so the bandit purely
     exploits what it learned -- this is the "policy" being evaluated.
  3. HOLDOUT phase: both the frozen adaptive policy and the static baseline are
     scored, independently, against a *fresh* stream of `n_holdout` modules
     (disjoint from the training stream) and matched fresh SyntheticReviewer
     instances, so the comparison reflects generalization, not memorized
     training noise.

We still emit the raw online training curve (`training_windows.csv`) for
illustrative purposes -- it shows the exploration dynamics -- but the headline
comparison in `summary.json` is the holdout-phase result.
"""

from __future__ import annotations

import argparse
import csv
import json
import uuid
from pathlib import Path
from typing import Dict, List

from opspilot.governance.sentinel_policy.policy_agent import (
    DEFAULT_ARMS, GuardrailPolicyAgent, ModuleContext,
    CategoryDecision, GuardrailDecision, check_hard_constraints, _build_context_vector,
)
from opspilot.governance.sentinel_policy.risk_scoring import score_soft_risks
from opspilot.governance.sentinel_policy.synthetic_module_generator import (
    SyntheticModule, generate_module_stream,
)
from opspilot.governance.sentinel_policy.synthetic_reviewer import SyntheticReviewer


class StaticThresholdAgent:
    """Baseline: fixed uniform threshold per category, never updates. Mirrors the
    deterministic-bounds-only design shared by every surveyed guardrail layer."""

    def __init__(self, threshold: float = 0.25):
        self.threshold = threshold

    def evaluate(self, code_text, module_context: ModuleContext) -> GuardrailDecision:
        hard = check_hard_constraints(code_text)
        if hard is not None:
            return GuardrailDecision(decision_id=str(uuid.uuid4()), overall_decision="HARD_VIOLATION",
                                      hard_violation=hard, module_id=module_context.module_id)

        scores = score_soft_risks(code_text, module_context.risk_class)
        cat_decisions = []
        for cat_id, score in scores.items():
            ctx = _build_context_vector(cat_id, score, module_context)
            if score < self.threshold - 0.08:
                d = "APPROVE"
            elif score > self.threshold + 0.08:
                d = "REJECT"
            else:
                d = "ESCALATE"
            cat_decisions.append(CategoryDecision(category=cat_id, score=score, threshold=self.threshold,
                                                    decision=d, context_vector=ctx.tolist()))
        if any(c.decision == "REJECT" for c in cat_decisions):
            overall = "REJECT"
        elif any(c.decision == "ESCALATE" for c in cat_decisions):
            overall = "ESCALATE"
        else:
            overall = "APPROVE"
        return GuardrailDecision(decision_id=str(uuid.uuid4()), overall_decision=overall,
                                  category_decisions=cat_decisions, module_id=module_context.module_id)


def _score_stream(agent, modules, reviewer: SyntheticReviewer, learn: bool) -> List[Dict]:
    """Scores `modules` against `agent`, optionally feeding back human dispositions
    for online learning. Returns one row per category decision."""
    rows: List[Dict] = []
    for mod in modules:
        module_context = ModuleContext(module_id=mod.module_id, risk_class=mod.risk_class,
                                        complexity=min(1.0, sum(mod.true_density.values()) / 10.0))
        decision = agent.evaluate(mod.code_text, module_context)

        if decision.overall_decision == "HARD_VIOLATION":
            rows.append({"module_id": mod.module_id, "risk_class": mod.risk_class,
                         "category": None, "hard_violation": True,
                         "flagged": True, "overridden": False, "missed": False})
            continue

        per_cat_human = {}
        for cat in decision.category_decisions:
            human_approved = reviewer.disposition(cat.category, cat.decision, module_context.risk_class)
            per_cat_human[cat.category] = human_approved
            flagged = cat.decision != "APPROVE"
            rows.append({
                "module_id": mod.module_id, "risk_class": mod.risk_class, "category": cat.category,
                "hard_violation": False, "score": cat.score, "threshold": cat.threshold,
                "flagged": flagged, "overridden": flagged and human_approved,
                "missed": (not flagged) and (not human_approved),
            })

        if learn and hasattr(agent, "record_human_disposition"):
            agent.record_human_disposition(decision.decision_id, per_cat_human)

    return rows


def _windowed(rows: List[Dict], window: int) -> List[Dict]:
    windows = []
    scored_rows = [r for r in rows if not r["hard_violation"]]
    for start in range(0, len(scored_rows), window):
        chunk = scored_rows[start:start + window]
        if not chunk:
            continue
        n = len(chunk)
        flagged_n = sum(1 for r in chunk if r["flagged"])
        overridden_n = sum(1 for r in chunk if r["overridden"])
        windows.append({
            "window_start": start, "n": n,
            "flag_rate": round(flagged_n / n, 4),
            "wasted_escalation_rate": round(overridden_n / n, 4),
            "override_rate_given_flagged": round(overridden_n / max(1, flagged_n), 4),
            "miss_rate_given_approved": round(sum(1 for r in chunk if r["missed"]) / max(1, n - flagged_n), 4),
        })
    return windows


def _aggregate(rows: List[Dict]) -> Dict:
    scored = [r for r in rows if not r["hard_violation"]]
    n = len(scored)
    flagged = sum(1 for r in scored if r["flagged"])
    overridden = sum(1 for r in scored if r["overridden"])
    return {
        "n_category_decisions": n,
        "flag_rate": round(flagged / max(1, n), 4),
        "wasted_escalation_rate": round(overridden / max(1, n), 4),
        "override_rate_given_flagged": round(overridden / max(1, flagged), 4),
        "miss_rate_given_approved": round(sum(1 for r in scored if r["missed"]) / max(1, n - flagged), 4),
    }


def _inject_hard_violations(modules: List[SyntheticModule], n: int) -> List[SyntheticModule]:
    modules = list(modules)
    if not modules:
        return modules
    step = max(1, len(modules) // (n + 1))
    for i in range(n):
        idx = min((i + 1) * step, len(modules) - 1)
        violating_code = (
            'package com.opspilot.modernized;\n'
            f'public class InjectedViolation{i} {{\n'
            '    public void run() { System.exit(1); }\n'
            '}\n'
        )
        modules[idx] = SyntheticModule(module_id=modules[idx].module_id, risk_class=modules[idx].risk_class,
                                        code_text=violating_code, true_density={})
    return modules


def run_evaluation(
    n_train: int = 4000,
    n_holdout: int = 800,
    train_seed: int = 42,
    holdout_seed: int = 777,
    window: int = 200,
    static_threshold: float = 0.25,
    n_injected_violations: int = 6,
    output_dir: Path = Path("workspace/sentinel_eval"),
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- TRAIN ---
    train_modules = generate_module_stream(n_modules=n_train, seed=train_seed)
    train_modules = _inject_hard_violations(train_modules, n_injected_violations)
    train_reviewer = SyntheticReviewer(seed=train_seed + 1)
    adaptive_agent = GuardrailPolicyAgent(arms=DEFAULT_ARMS, seed=train_seed)
    train_rows = _score_stream(adaptive_agent, train_modules, train_reviewer, learn=True)
    training_windows = _windowed(train_rows, window)

    # --- FREEZE ---
    adaptive_agent.freeze()

    # --- HOLDOUT ---
    holdout_modules = generate_module_stream(n_modules=n_holdout, seed=holdout_seed)
    holdout_modules = _inject_hard_violations(holdout_modules, max(1, n_injected_violations // 2))
    holdout_reviewer_static = SyntheticReviewer(seed=holdout_seed + 1)
    holdout_reviewer_adaptive = SyntheticReviewer(seed=holdout_seed + 1)  # identical reviewer, fair comparison

    static_agent = StaticThresholdAgent(static_threshold)
    static_rows = _score_stream(static_agent, holdout_modules, holdout_reviewer_static, learn=False)
    adaptive_rows = _score_stream(adaptive_agent, holdout_modules, holdout_reviewer_adaptive, learn=False)

    static_windows = _windowed(static_rows, window)
    adaptive_windows = _windowed(adaptive_rows, window)

    static_agg = _aggregate(static_rows)
    adaptive_agg = _aggregate(adaptive_rows)

    n_injected_holdout = max(1, n_injected_violations // 2)
    static_hard_catches = sum(1 for r in static_rows if r["hard_violation"])
    adaptive_hard_catches = sum(1 for r in adaptive_rows if r["hard_violation"])

    summary = {
        "n_train": n_train,
        "n_holdout": n_holdout,
        "static_threshold": static_threshold,
        "n_injected_hard_violations_holdout": n_injected_holdout,
        "static_hard_violation_catch_rate": static_hard_catches / n_injected_holdout,
        "adaptive_hard_violation_catch_rate": adaptive_hard_catches / n_injected_holdout,
        "holdout_static": static_agg,
        "holdout_adaptive_frozen": adaptive_agg,
        "wasted_escalation_rate_relative_change": (
            round((adaptive_agg["wasted_escalation_rate"] - static_agg["wasted_escalation_rate"])
                  / max(1e-9, static_agg["wasted_escalation_rate"]), 4)
        ),
        "training_curve_first_window_wasted_escalation_rate": training_windows[0]["wasted_escalation_rate"] if training_windows else None,
        "training_curve_last_window_wasted_escalation_rate": training_windows[-1]["wasted_escalation_rate"] if training_windows else None,
    }

    fieldnames = ["window_start", "n", "flag_rate", "wasted_escalation_rate",
                  "override_rate_given_flagged", "miss_rate_given_approved"]
    for name, rows in [("training_windows", training_windows), ("holdout_static_windows", static_windows),
                        ("holdout_adaptive_windows", adaptive_windows)]:
        with open(output_dir / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary, training_windows, static_windows, adaptive_windows


def main():
    parser = argparse.ArgumentParser(description="Run SentinelPolicy train/freeze/holdout evaluation")
    parser.add_argument("--n-train", type=int, default=4000)
    parser.add_argument("--n-holdout", type=int, default=800)
    parser.add_argument("--train-seed", type=int, default=42)
    parser.add_argument("--holdout-seed", type=int, default=777)
    parser.add_argument("--window", type=int, default=200)
    parser.add_argument("--static-threshold", type=float, default=0.25)
    parser.add_argument("--output-dir", type=str, default="workspace/sentinel_eval")
    args = parser.parse_args()

    summary, *_ = run_evaluation(
        n_train=args.n_train, n_holdout=args.n_holdout, train_seed=args.train_seed,
        holdout_seed=args.holdout_seed, window=args.window, static_threshold=args.static_threshold,
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
