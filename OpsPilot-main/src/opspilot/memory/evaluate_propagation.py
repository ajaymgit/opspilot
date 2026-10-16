"""Evaluation harness for RepoMind's change-propagation mechanism.

Three conditions, replayed over the same synthetic repo and the same set of
injected field-level breaking changes:

  1. NO_PROPAGATION: only modules edited in the current commit are
     re-verified (nothing, in this experiment, since the edit is to a shared
     copybook, not a module) -- models a team with no automated propagation.
  2. VERIFY_EVERYTHING: re-verify the entire repo on every change --
     recall is always 1.0 by construction, but precision equals
     |truly impacted| / |repo size|, typically small.
  3. REPO_MIND: re-verify `RepoDependencyGraph.structural_dependents` of the
     changed copybook -- conservative by design (recall should be 1.0, since
     every truly-impacted module is, by construction, also a structural
     dependent), with precision between the other two conditions.

Precision/recall are computed against `truly_impacted_modules`, the
field-level ground truth the synthetic generator tracks separately from the
(module-granularity) dependency graph itself.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Dict, List, Set

from opspilot.memory.change_propagation_agent import ChangePropagationAgent
from opspilot.memory.synthetic_repo_generator import (
    SyntheticRepo, generate_synthetic_repo, truly_impacted_modules,
)


def _prf(predicted: Set[str], truth: Set[str]) -> Dict[str, float]:
    if not truth and not predicted:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    tp = len(predicted & truth)
    precision = tp / len(predicted) if predicted else (1.0 if not truth else 0.0)
    recall = tp / len(truth) if truth else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def _run_scenario(repo: SyntheticRepo, changed_copybook: str, changed_field: str) -> Dict:
    truth = truly_impacted_modules(repo, changed_copybook, changed_field)

    agent = ChangePropagationAgent(repo.repo_graph)
    repo_mind_result = agent.propagate(changed_copybook)
    repo_mind_predicted = set(repo_mind_result.scheduled_for_reverification)

    no_propagation_predicted: Set[str] = set()
    verify_everything_predicted = set(repo.modules)

    return {
        "changed_copybook": changed_copybook,
        "changed_field": changed_field,
        "n_truly_impacted": len(truth),
        "n_repo_modules": len(repo.modules),
        "no_propagation": {**_prf(no_propagation_predicted, truth), "n_flagged": 0},
        "verify_everything": {**_prf(verify_everything_predicted, truth), "n_flagged": len(verify_everything_predicted)},
        "repo_mind": {**_prf(repo_mind_predicted, truth), "n_flagged": len(repo_mind_predicted)},
    }


def run_evaluation(
    n_modules: int = 80,
    n_copybooks: int = 12,
    n_scenarios: int = 150,
    seed: int = 42,
    output_dir: Path = Path("workspace/repomind_eval"),
) -> Dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    repo = generate_synthetic_repo(n_modules=n_modules, n_copybooks=n_copybooks, seed=seed)
    rng = random.Random(seed + 1)

    scenarios: List[Dict] = []
    for _ in range(n_scenarios):
        cpy = rng.choice(repo.copybooks)
        field_choices = repo.copybook_fields[cpy]
        changed_field = rng.choice(field_choices)
        scenarios.append(_run_scenario(repo, cpy, changed_field))

    def _avg(condition: str, key: str, scenario_subset=None) -> float:
        subset = scenario_subset if scenario_subset is not None else scenarios
        if not subset:
            return None
        return round(sum(s[condition][key] for s in subset) / len(subset), 4)

    nontrivial_scenarios = [s for s in scenarios if s["n_truly_impacted"] > 0]

    summary = {
        "n_modules": n_modules,
        "n_copybooks": n_copybooks,
        "n_scenarios": n_scenarios,
        "n_nontrivial_scenarios": len(nontrivial_scenarios),
        "avg_truly_impacted_per_scenario": round(sum(s["n_truly_impacted"] for s in scenarios) / n_scenarios, 3),
        "no_propagation": {
            "avg_precision": _avg("no_propagation", "precision"),
            "avg_recall": _avg("no_propagation", "recall"),
            "avg_f1": _avg("no_propagation", "f1"),
            "avg_n_flagged": _avg("no_propagation", "n_flagged"),
            "avg_recall_nontrivial_only": _avg("no_propagation", "recall", nontrivial_scenarios),
        },
        "verify_everything": {
            "avg_precision": _avg("verify_everything", "precision"),
            "avg_recall": _avg("verify_everything", "recall"),
            "avg_f1": _avg("verify_everything", "f1"),
            "avg_n_flagged": _avg("verify_everything", "n_flagged"),
            "avg_precision_nontrivial_only": _avg("verify_everything", "precision", nontrivial_scenarios),
        },
        "repo_mind": {
            "avg_precision": _avg("repo_mind", "precision"),
            "avg_recall": _avg("repo_mind", "recall"),
            "avg_f1": _avg("repo_mind", "f1"),
            "avg_n_flagged": _avg("repo_mind", "n_flagged"),
            "avg_precision_nontrivial_only": _avg("repo_mind", "precision", nontrivial_scenarios),
            "avg_recall_nontrivial_only": _avg("repo_mind", "recall", nontrivial_scenarios),
        },
    }
    summary["repo_mind_scope_reduction_vs_verify_everything_pct"] = round(
        100.0 * (1 - summary["repo_mind"]["avg_n_flagged"] / max(1e-9, summary["verify_everything"]["avg_n_flagged"])), 2
    )

    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    with open(output_dir / "scenarios.json", "w", encoding="utf-8") as f:
        json.dump(scenarios, f, indent=2)

    return summary, scenarios


def main():
    parser = argparse.ArgumentParser(description="Run RepoMind propagation evaluation")
    parser.add_argument("--n-modules", type=int, default=80)
    parser.add_argument("--n-copybooks", type=int, default=12)
    parser.add_argument("--n-scenarios", type=int, default=150)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=str, default="workspace/repomind_eval")
    args = parser.parse_args()

    summary, _ = run_evaluation(n_modules=args.n_modules, n_copybooks=args.n_copybooks,
                                 n_scenarios=args.n_scenarios, seed=args.seed, output_dir=Path(args.output_dir))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
