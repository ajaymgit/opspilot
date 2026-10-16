"""Tracks the delta_t (Verifier-reported failure count) trajectory across
self-refine iterations and classifies it as improving, converged, or plateaued.

This is the online half of RefineRL: the Pre-Refinement Predictor sets a
*starting* budget from static features, but the actual convergence behavior of
a specific module can only be observed once refinement is underway. The
Trajectory Monitor is what lets the Dynamic Budget Adjuster react to that
observed behavior rather than blindly grinding through a fixed budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class TrajectoryStatus:
    iteration: int
    failure_count: int
    previous_failure_count: int
    is_improving: bool
    is_plateaued: bool
    is_converged: bool
    relative_improvement: float  # vs. previous iteration; negative = regressed


@dataclass
class TrajectoryMonitor:
    plateau_window: int = 3
    plateau_relative_threshold: float = 0.08
    history: List[int] = field(default_factory=list)

    def observe(self, failure_count: int) -> TrajectoryStatus:
        self.history.append(failure_count)
        iteration = len(self.history)
        is_converged = failure_count == 0

        if iteration == 1:
            return TrajectoryStatus(iteration=1, failure_count=failure_count, previous_failure_count=failure_count,
                                     is_improving=True, is_plateaued=False, is_converged=is_converged,
                                     relative_improvement=0.0)

        prev = self.history[-2]
        relative_improvement = (prev - failure_count) / max(1, prev)
        is_improving = failure_count < prev
        is_plateaued = (not is_converged) and self._check_plateau()

        return TrajectoryStatus(iteration=iteration, failure_count=failure_count, previous_failure_count=prev,
                                 is_improving=is_improving, is_plateaued=is_plateaued, is_converged=is_converged,
                                 relative_improvement=relative_improvement)

    def _check_plateau(self) -> bool:
        """A plateau is declared only when there has been NO net improvement
        at all over the last `plateau_window` iterations (current count >= the
        count from `plateau_window` iterations ago). A softer "small relative
        drop" criterion looks appealing but is unreliable here: rounding a
        slowly, genuinely decaying failure count to an integer routinely
        produces several consecutive equal-looking values before ticking down
        (e.g. 3.6 -> 3.4 -> 3.2 all round to 3) -- that is normal progress
        that just hasn't crossed an integer boundary yet, not a stall. Only a
        strict "no net decrease at all" test reliably distinguishes a truly
        stalled module from a slow-but-real one."""
        if len(self.history) < self.plateau_window + 1:
            return False
        window = self.history[-(self.plateau_window + 1):]
        start, end = window[0], window[-1]
        if start == 0:
            return False  # already converged, not a plateau
        return end >= start
