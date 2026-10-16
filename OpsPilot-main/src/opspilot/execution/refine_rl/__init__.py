"""RefineRL: predictive, per-module iteration-budget allocation for the
Phase 3 self-refine loop (Coder <-> Verifier).

Implements the research direction named in Section VI of the survey: the
self-refine cycle "typically converges within 3-5 iterations for well-structured
COBOL modules but may need up to 12 for modules with embedded SQL or CICS
handlers, motivating an adaptive rather than fixed iteration budget B" -- named
directly, never built, in the surveyed literature (every surveyed self-refine
implementation, including Eq. 1 of the survey itself and TheBotCompany, uses one
fixed B for the whole run).

Design summary
---------------
    Pre-Refinement Predictor (`predictor.py`)
        Predicts a per-module starting iteration budget from Discovery-time
        features (embedded-SQL flag, CICS-handler flag, cyclomatic complexity,
        dependency count) BEFORE the first Coder attempt.

    Trajectory Monitor (`trajectory_monitor.py`)
        After each self-refine iteration, tracks whether Verifier-reported
        failures are shrinking, plateaued, or diverging.

    Dynamic Budget Adjuster (`budget_adjuster.py`)
        Shortens the remaining budget when convergence is faster than
        predicted; triggers early HITL escalation when the trajectory has
        plateaued well before the predicted budget is exhausted.

The standard Coder/Verifier mechanics are untouched -- this package wraps
*budget logic* around the existing loop (`opspilot.execution.self_refine_loop`),
consistent with the idea write-up's framing ("this project wraps the budget
logic around the existing loop, doesn't replace it").
"""

from opspilot.execution.refine_rl.module_features import ModuleFeatures, extract_module_features
from opspilot.execution.refine_rl.predictor import IterationBudgetPredictor
from opspilot.execution.refine_rl.trajectory_monitor import TrajectoryMonitor, TrajectoryStatus
from opspilot.execution.refine_rl.budget_adjuster import DynamicBudgetAdjuster, BudgetDecision

__all__ = [
    "ModuleFeatures",
    "extract_module_features",
    "IterationBudgetPredictor",
    "TrajectoryMonitor",
    "TrajectoryStatus",
    "DynamicBudgetAdjuster",
    "BudgetDecision",
]
