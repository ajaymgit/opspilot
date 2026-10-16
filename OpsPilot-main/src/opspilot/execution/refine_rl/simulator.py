"""Generates synthetic self-refine (Coder<->Verifier) trajectories with a known
ground-truth convergence iteration, parameterized by module features.

Used only for offline training/evaluation of the Pre-Refinement Predictor and
the RefineRL budget-allocation policy -- exactly the role the idea write-up's
own "Dataset" section describes ("run the synthetic COBOL benchmark through a
standard self-refine loop first to generate the historical... training data").
The mocked `autogen` backend in this repository always succeeds on the first
turn or fails identically forever (see `src/autogen/__init__.py`), so it has no
notion of a gradually-shrinking failure trajectory; this generator supplies
that signal synthetically, calibrated to the *shape* the survey reports
(3-5 iterations for well-structured modules, up to 12 for modules with embedded
SQL/CICS handlers) rather than to any single team's exact numbers.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Optional

from opspilot.execution.refine_rl.module_features import ModuleFeatures


@dataclass
class SimulatedTrajectory:
    module_id: str
    features: ModuleFeatures
    true_convergence_iteration: Optional[int]  # None if genuinely unconvergeable
    failure_counts: List[int] = field(default_factory=list)  # per iteration, 1-indexed
    convergeable: bool = True


def _sample_true_iteration(rng: random.Random, features: ModuleFeatures):
    base = rng.gauss(3.0, 0.6)
    if features.embedded_sql:
        base += rng.uniform(2.0, 5.0)
    if features.cics_handler:
        base += rng.uniform(3.0, 6.0)
    base += max(0.0, features.cyclomatic_complexity - 3.0) * rng.uniform(0.15, 0.35)
    base += features.dependency_count * rng.uniform(0.05, 0.15)
    true_iter = max(1, round(base))

    p_unconvergeable = 0.02 + (0.05 if features.cics_handler else 0.0) + (0.03 if features.embedded_sql else 0.0)
    convergeable = rng.random() > p_unconvergeable
    return (true_iter if convergeable else None), convergeable


def generate_trajectory(rng: random.Random, module_id: str, features: ModuleFeatures, cap: int = 20) -> SimulatedTrajectory:
    true_iter, convergeable = _sample_true_iteration(rng, features)

    # Initial failure count scales with both module complexity and the number
    # of steps the trajectory will take to resolve. This is not just a curve-
    # fitting convenience: a module that needs many refinement passes is
    # plausibly also one with a larger surface of test cases (more CICS/SQL
    # edge cases, more dependent call sites), so a richer initial failure
    # count for longer trajectories is a defensible modeling choice, not only
    # a technical one -- and it matters technically too, because a failure
    # count with too little dynamic range relative to its trajectory length
    # spends many consecutive iterations rounding to the same integer, which
    # is indistinguishable from a genuine stall to any plateau detector
    # working off the raw count.
    reference_length = true_iter if convergeable else max(6, round(2.0 + features.cyclomatic_complexity / 2.0))
    f0 = max(4.0, reference_length * rng.uniform(0.85, 1.25))

    failure_counts: List[int] = []
    if convergeable:
        tau = max(0.6, true_iter / 2.3)
        for k in range(1, cap + 1):
            projected = f0 * math.exp(-k / tau)
            noisy = round(projected + rng.gauss(0, 0.4))
            if k >= true_iter:
                noisy = 0
            else:
                # never let noise round down to "converged" before the declared
                # true convergence iteration -- otherwise the observable
                # trajectory would be inconsistent with its own ground truth,
                # and evaluation metrics keyed on true_convergence_iteration
                # would silently be comparing against the wrong point.
                noisy = max(1, noisy)
            failure_counts.append(noisy)
            if noisy == 0:
                break
    else:
        # genuinely hard module: failures plateau above zero and never resolve
        floor = max(1, round(f0 * 0.3))
        decay_target = max(6, round(f0))
        for k in range(1, cap + 1):
            projected = floor + (f0 - floor) * math.exp(-k / max(1.0, decay_target / 2.0))
            noisy = max(floor, round(projected + rng.gauss(0, 0.3)))
            failure_counts.append(noisy)

    return SimulatedTrajectory(module_id=module_id, features=features, true_convergence_iteration=true_iter,
                                failure_counts=failure_counts, convergeable=convergeable)


def _sample_features(rng: random.Random) -> ModuleFeatures:
    embedded_sql = rng.random() < 0.35
    cics_handler = rng.random() < 0.20 and embedded_sql  # CICS modules are typically also SQL-bearing here
    cyclomatic_complexity = max(1.0, rng.gauss(9.0, 5.0))
    dependency_count = max(0, round(rng.gauss(4.0, 3.0)))
    return ModuleFeatures(embedded_sql=embedded_sql, cics_handler=cics_handler,
                           cyclomatic_complexity=cyclomatic_complexity, dependency_count=dependency_count)


def generate_trajectory_dataset(n_modules: int, seed: int = 42, cap: int = 20) -> List[SimulatedTrajectory]:
    rng = random.Random(seed)
    trajectories = []
    for i in range(n_modules):
        features = _sample_features(rng)
        trajectories.append(generate_trajectory(rng, module_id=f"{i:04d}", features=features, cap=cap))
    return trajectories
