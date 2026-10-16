"""Dynamic Budget Adjuster: reconciles the Pre-Refinement Predictor's initial
guess against what the Trajectory Monitor is actually observing.

Two failure modes of a single fixed budget B, per the idea write-up:
  - set high: most modules converge early and waste the unused budget headroom
    (in a real system this shows up as unnecessary iteration/token spend, since
    a well-behaved run simply stops at convergence either way -- the waste is
    opportunity cost, not literal wasted calls).
  - set low: modules that hit a bad early attempt are prematurely escalated
    even though they would have converged with 1-2 more iterations.

The Dynamic Budget Adjuster narrows `remaining_budget` downward when the
trajectory is converging faster than the initial prediction (nothing to gain by
keeping a large budget open), and recommends early escalation when the
trajectory has plateaued well before the predicted budget is exhausted (nothing
to gain by continuing to grind).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from opspilot.execution.refine_rl.trajectory_monitor import TrajectoryStatus


class BudgetDecision(Enum):
    CONTINUE = "CONTINUE"
    CONVERGED = "CONVERGED"
    SHORTEN = "SHORTEN"
    EXTENDED = "EXTENDED"
    ESCALATE_EARLY = "ESCALATE_EARLY"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass
class DynamicBudgetAdjuster:
    predicted_budget: int
    min_budget: int = 2
    max_budget_cap: int = 20
    extend_increment: int = 3
    shorten_fast_improvement_threshold: float = 0.55
    shorten_headroom_iterations: int = 3
    shorten_min_previous_failure_count: int = 4

    def __post_init__(self):
        self.remaining_budget = max(self.min_budget, self.predicted_budget)
        self._shortened = False
        self._extensions_granted = 0

    def decide(self, status: TrajectoryStatus) -> BudgetDecision:
        if status.is_converged:
            return BudgetDecision.CONVERGED

        if status.is_plateaued:
            # A plateau is a reason to stop regardless of remaining budget --
            # continuing would not help, so this check runs before the
            # exhaustion/extension logic below.
            return BudgetDecision.ESCALATE_EARLY

        if status.iteration >= self.remaining_budget:
            # The predictor's starting guess was too low, but the trajectory
            # is still genuinely improving (not plateaued, or it would have
            # been caught above) -- extend rather than cut off a module that
            # is clearly on track to converge. This is bounded by
            # `max_budget_cap` so a pathological "improving by 1 every time"
            # trajectory cannot run forever.
            if status.is_improving and self.remaining_budget < self.max_budget_cap:
                self.remaining_budget = min(self.max_budget_cap, self.remaining_budget + self.extend_increment)
                self._extensions_granted += 1
                return BudgetDecision.EXTENDED
            return BudgetDecision.BUDGET_EXHAUSTED

        if (status.is_improving
                and status.relative_improvement >= self.shorten_fast_improvement_threshold
                and status.iteration >= 2
                # relative improvement is a noisy, unreliable signal once the
                # failure count is already small (e.g. 3 -> 1 is a "67%"
                # improvement but is just integer-rounding noise, not evidence
                # the module is converging unusually fast) -- only shorten off
                # of a drop that started from a reasonably large count.
                and status.previous_failure_count >= self.shorten_min_previous_failure_count):
            projected_convergence = status.iteration + self.shorten_headroom_iterations
            if projected_convergence < self.remaining_budget:
                self.remaining_budget = max(self.min_budget, projected_convergence)
                self._shortened = True
                return BudgetDecision.SHORTEN

        return BudgetDecision.CONTINUE
