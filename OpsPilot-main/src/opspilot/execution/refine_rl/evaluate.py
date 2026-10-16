"""Evaluation harness for RefineRL.

Three-condition experiment, per the idea write-up's own "Experimental Setup":

  1. FIXED_LOW: every module gets the survey's low-end fixed budget (B=4).
     Cheap, but modules that genuinely need more iterations get escalated
     before they would have converged (a "premature escalation").
  2. FIXED_HIGH: every module gets the survey's high-end fixed budget (B=12).
     Safe (rarely escalates a module that would have converged), but burns
     the full budget on both slow-converging AND genuinely-unconvergeable
     modules that a plateau detector would have caught much earlier.
  3. REFINE_RL: a per-module predicted starting budget (from the trained
     Pre-Refinement Predictor) plus online adjustment (shorten when
     converging fast, escalate early on a detected plateau).

All three conditions replay the SAME underlying synthetic trajectories (so the
comparison is apples-to-apples: identical modules, identical "true" refinement
behavior, only the budget policy differs).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

from opspilot.execution.refine_rl.budget_adjuster import BudgetDecision, DynamicBudgetAdjuster
from opspilot.execution.refine_rl.predictor import IterationBudgetPredictor
from opspilot.execution.refine_rl.simulator import SimulatedTrajectory, generate_trajectory_dataset
from opspilot.execution.refine_rl.trajectory_monitor import TrajectoryMonitor


@dataclass
class RunResult:
    module_id: str
    convergeable: bool
    true_convergence_iteration: int  # -1 if genuinely unconvergeable
    iterations_used: int
    outcome: str  # CONVERGED | BUDGET_EXHAUSTED | ESCALATED_EARLY
    premature: bool  # convergeable module that was NOT converged by the time it stopped
    budget_assigned: int


def _run_fixed_budget(trajectory: SimulatedTrajectory, budget: int) -> RunResult:
    for k, failures in enumerate(trajectory.failure_counts[:budget], start=1):
        if failures == 0:
            return RunResult(trajectory.module_id, trajectory.convergeable,
                              trajectory.true_convergence_iteration or -1, k, "CONVERGED", False, budget)
    used = min(budget, len(trajectory.failure_counts))
    premature = trajectory.convergeable and (
        trajectory.true_convergence_iteration is not None and trajectory.true_convergence_iteration > budget
    )
    return RunResult(trajectory.module_id, trajectory.convergeable,
                      trajectory.true_convergence_iteration or -1, used, "BUDGET_EXHAUSTED", premature, budget)


def _run_refine_rl(trajectory: SimulatedTrajectory, predictor: IterationBudgetPredictor) -> RunResult:
    predicted_budget = predictor.predict(trajectory.features)
    adjuster = DynamicBudgetAdjuster(predicted_budget=predicted_budget)
    monitor = TrajectoryMonitor()

    last_iteration = 0
    for k, failures in enumerate(trajectory.failure_counts, start=1):
        status = monitor.observe(failures)
        decision = adjuster.decide(status)
        last_iteration = k

        if decision == BudgetDecision.CONVERGED:
            return RunResult(trajectory.module_id, trajectory.convergeable,
                              trajectory.true_convergence_iteration or -1, k, "CONVERGED", False, predicted_budget)
        if decision == BudgetDecision.ESCALATE_EARLY:
            premature = trajectory.convergeable and (
                trajectory.true_convergence_iteration is not None and trajectory.true_convergence_iteration > k
            )
            return RunResult(trajectory.module_id, trajectory.convergeable,
                              trajectory.true_convergence_iteration or -1, k, "ESCALATED_EARLY", premature, predicted_budget)
        if decision == BudgetDecision.BUDGET_EXHAUSTED:
            premature = trajectory.convergeable and (
                trajectory.true_convergence_iteration is not None and trajectory.true_convergence_iteration > k
            )
            return RunResult(trajectory.module_id, trajectory.convergeable,
                              trajectory.true_convergence_iteration or -1, k, "BUDGET_EXHAUSTED", premature, predicted_budget)
        # CONTINUE / SHORTEN / EXTENDED -> keep going

    # trajectory array exhausted without a terminal decision (cap reached)
    premature = trajectory.convergeable and (
        trajectory.true_convergence_iteration is not None and trajectory.true_convergence_iteration > last_iteration
    )
    return RunResult(trajectory.module_id, trajectory.convergeable,
                      trajectory.true_convergence_iteration or -1, last_iteration, "BUDGET_EXHAUSTED", premature,
                      predicted_budget)


def _summarize(results: List[RunResult]) -> Dict:
    n = len(results)
    convergeable = [r for r in results if r.convergeable]
    unconvergeable = [r for r in results if not r.convergeable]

    total_iterations = sum(r.iterations_used for r in results)
    convergence_rate = (sum(1 for r in convergeable if r.outcome == "CONVERGED") / max(1, len(convergeable)))
    premature_escalation_rate = (sum(1 for r in convergeable if r.premature) / max(1, len(convergeable)))
    # for genuinely unconvergeable modules, did the condition stop before burning its full assigned budget?
    avg_iterations_on_unconvergeable = (
        sum(r.iterations_used for r in unconvergeable) / max(1, len(unconvergeable))
    )

    return {
        "n_modules": n,
        "n_convergeable": len(convergeable),
        "n_unconvergeable": len(unconvergeable),
        "total_iterations_consumed": total_iterations,
        "avg_iterations_per_module": round(total_iterations / max(1, n), 3),
        "convergence_rate": round(convergence_rate, 4),
        "premature_escalation_rate": round(premature_escalation_rate, 4),
        "avg_iterations_on_unconvergeable_modules": round(avg_iterations_on_unconvergeable, 3),
    }


def run_evaluation(
    n_train: int = 1500,
    n_holdout: int = 600,
    train_seed: int = 42,
    holdout_seed: int = 777,
    fixed_low: int = 4,
    fixed_high: int = 12,
    output_dir: Path = Path("workspace/refine_rl_eval"),
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    train_trajectories = generate_trajectory_dataset(n_train, seed=train_seed)
    holdout_trajectories = generate_trajectory_dataset(n_holdout, seed=holdout_seed)

    # train predictor on train set; censor unconvergeable modules at the cap
    # length so the predictor learns "this class of module needs the max
    # budget" rather than being trained on an undefined target
    train_features = [t.features for t in train_trajectories]
    train_targets = [
        t.true_convergence_iteration if t.convergeable else len(t.failure_counts)
        for t in train_trajectories
    ]
    predictor = IterationBudgetPredictor()
    predictor.fit(train_features, train_targets)

    fixed_low_results = [_run_fixed_budget(t, fixed_low) for t in holdout_trajectories]
    fixed_high_results = [_run_fixed_budget(t, fixed_high) for t in holdout_trajectories]
    refine_rl_results = [_run_refine_rl(t, predictor) for t in holdout_trajectories]

    summary = {
        "n_train": n_train,
        "n_holdout": n_holdout,
        "predictor_trained": predictor.is_trained,
        "fixed_low_budget": fixed_low,
        "fixed_high_budget": fixed_high,
        "fixed_low": _summarize(fixed_low_results),
        "fixed_high": _summarize(fixed_high_results),
        "refine_rl": _summarize(refine_rl_results),
    }
    summary["iteration_savings_vs_fixed_high_pct"] = round(
        100.0 * (1 - summary["refine_rl"]["total_iterations_consumed"] / max(1, summary["fixed_high"]["total_iterations_consumed"])), 2
    )
    summary["convergence_rate_gap_vs_fixed_high_pct"] = round(
        100.0 * (summary["fixed_high"]["convergence_rate"] - summary["refine_rl"]["convergence_rate"]), 2
    )

    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(output_dir / "per_module_results.json", "w", encoding="utf-8") as f:
        json.dump({
            "fixed_low": [asdict(r) for r in fixed_low_results],
            "fixed_high": [asdict(r) for r in fixed_high_results],
            "refine_rl": [asdict(r) for r in refine_rl_results],
        }, f, indent=2)

    return summary, fixed_low_results, fixed_high_results, refine_rl_results


def run_budget_sweep(
    n_train: int = 1500,
    n_holdout: int = 600,
    train_seed: int = 42,
    holdout_seed: int = 777,
    sweep_budgets=(3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16),
    output_dir: Path = Path("workspace/refine_rl_eval"),
):
    """Traces the achievable cost/convergence-rate frontier for single, fixed,
    population-wide budgets, and reports where RefineRL's adaptive, per-module
    policy lands relative to it. This is the fairer comparison: it is easy to
    make an adaptive policy look good against a badly-chosen fixed budget, but
    the real question is whether it beats the best a fixed budget could do --
    and, just as importantly, whether it does so without requiring the
    operator to already know what that best fixed value is.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    train_trajectories = generate_trajectory_dataset(n_train, seed=train_seed)
    holdout_trajectories = generate_trajectory_dataset(n_holdout, seed=holdout_seed)

    train_features = [t.features for t in train_trajectories]
    train_targets = [
        t.true_convergence_iteration if t.convergeable else len(t.failure_counts)
        for t in train_trajectories
    ]
    predictor = IterationBudgetPredictor()
    predictor.fit(train_features, train_targets)

    frontier = []
    for b in sweep_budgets:
        results = [_run_fixed_budget(t, b) for t in holdout_trajectories]
        summary = _summarize(results)
        summary["budget"] = b
        frontier.append(summary)

    refine_rl_results = [_run_refine_rl(t, predictor) for t in holdout_trajectories]
    refine_rl_summary = _summarize(refine_rl_results)

    with open(output_dir / "frontier.json", "w", encoding="utf-8") as f:
        json.dump({"fixed_budget_frontier": frontier, "refine_rl": refine_rl_summary}, f, indent=2)

    return frontier, refine_rl_summary


def main():
    parser = argparse.ArgumentParser(description="Run RefineRL evaluation")
    parser.add_argument("--n-train", type=int, default=1500)
    parser.add_argument("--n-holdout", type=int, default=600)
    parser.add_argument("--train-seed", type=int, default=42)
    parser.add_argument("--holdout-seed", type=int, default=777)
    parser.add_argument("--fixed-low", type=int, default=4)
    parser.add_argument("--fixed-high", type=int, default=12)
    parser.add_argument("--sweep", action="store_true", help="Also trace the fixed-budget frontier")
    parser.add_argument("--output-dir", type=str, default="workspace/refine_rl_eval")
    args = parser.parse_args()

    summary, *_ = run_evaluation(
        n_train=args.n_train, n_holdout=args.n_holdout, train_seed=args.train_seed,
        holdout_seed=args.holdout_seed, fixed_low=args.fixed_low, fixed_high=args.fixed_high,
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(summary, indent=2))

    if args.sweep:
        frontier, rl_summary = run_budget_sweep(
            n_train=args.n_train, n_holdout=args.n_holdout, train_seed=args.train_seed,
            holdout_seed=args.holdout_seed, output_dir=Path(args.output_dir),
        )
        print(json.dumps({"fixed_budget_frontier": frontier, "refine_rl": rl_summary}, indent=2))


if __name__ == "__main__":
    main()
