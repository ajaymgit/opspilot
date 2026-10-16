"""Unit tests for RefineRL: predictive iteration-budget allocation (Idea 8)."""

from pathlib import Path

from opspilot.execution.refine_rl.budget_adjuster import BudgetDecision, DynamicBudgetAdjuster
from opspilot.execution.refine_rl.evaluate import _run_fixed_budget, _run_refine_rl, run_evaluation
from opspilot.execution.refine_rl.module_features import ModuleFeatures, extract_module_features
from opspilot.execution.refine_rl.predictor import IterationBudgetPredictor
from opspilot.execution.refine_rl.simulator import generate_trajectory, generate_trajectory_dataset
from opspilot.execution.refine_rl.trajectory_monitor import TrajectoryMonitor


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def test_extract_module_features_detects_embedded_sql_and_cics():
    analysis_output = {
        "embedded_sql": [{"statement_type": "EXEC CICS READ"}],
        "sections_or_procedures": [{"name": "1000-CICS-READ-RECORD"}],
        "call_graph": {"edges": [("A", "B"), ("B", "C")]},
        "copybooks_or_includes": ["CUSTOMER-REC"],
        "external_calls": [],
    }
    features = extract_module_features(analysis_output)
    assert features.embedded_sql is True
    assert features.cics_handler is True
    assert features.dependency_count == 1


def test_extract_module_features_clean_module():
    analysis_output = {
        "embedded_sql": [],
        "sections_or_procedures": [{"name": "1000-VALIDATE-INPUT"}],
        "call_graph": {"edges": []},
        "copybooks_or_includes": [],
        "external_calls": [],
    }
    features = extract_module_features(analysis_output)
    assert features.embedded_sql is False
    assert features.cics_handler is False


# ---------------------------------------------------------------------------
# Trajectory monitor
# ---------------------------------------------------------------------------

def test_trajectory_monitor_detects_convergence():
    monitor = TrajectoryMonitor()
    monitor.observe(5)
    monitor.observe(3)
    status = monitor.observe(0)
    assert status.is_converged is True
    assert status.is_plateaued is False


def test_trajectory_monitor_detects_genuine_plateau():
    monitor = TrajectoryMonitor(plateau_window=3)
    for f in [6, 6, 6, 6]:
        status = monitor.observe(f)
    assert status.is_plateaued is True


def test_trajectory_monitor_does_not_flag_slow_but_real_progress_as_plateau():
    """A trajectory that is monotonically (if slowly) decreasing must never be
    classified as a plateau, since it is not one -- this is the regression
    test for the "integer-rounding looks like a stall" failure mode found
    during evaluation-harness development."""
    monitor = TrajectoryMonitor(plateau_window=3)
    status = None
    for f in [10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0]:
        status = monitor.observe(f)
        if not status.is_converged:
            assert status.is_plateaued is False


# ---------------------------------------------------------------------------
# Dynamic budget adjuster
# ---------------------------------------------------------------------------

def test_adjuster_converges_when_failure_count_hits_zero():
    adjuster = DynamicBudgetAdjuster(predicted_budget=5)
    monitor = TrajectoryMonitor()
    status = monitor.observe(0)
    assert adjuster.decide(status) == BudgetDecision.CONVERGED


def test_adjuster_escalates_early_on_plateau_before_budget_exhausted():
    adjuster = DynamicBudgetAdjuster(predicted_budget=10)
    monitor = TrajectoryMonitor(plateau_window=3)
    decision = None
    for f in [8, 8, 8, 8]:
        status = monitor.observe(f)
        decision = adjuster.decide(status)
    assert decision == BudgetDecision.ESCALATE_EARLY
    # crucially, this fired well before the predicted budget (10) was reached
    assert monitor.history[-1] != 0


def test_adjuster_extends_budget_for_a_still_improving_trajectory():
    """If the predicted budget was too conservative but the module is clearly
    still making progress (not plateaued), the adjuster should extend rather
    than force a premature BUDGET_EXHAUSTED."""
    adjuster = DynamicBudgetAdjuster(predicted_budget=3, extend_increment=3)
    monitor = TrajectoryMonitor(plateau_window=3)
    decisions = []
    for f in [9, 7, 5, 3, 1, 0]:
        status = monitor.observe(f)
        decisions.append(adjuster.decide(status))
    assert BudgetDecision.EXTENDED in decisions
    assert decisions[-1] == BudgetDecision.CONVERGED


def test_adjuster_never_flags_unconvergeable_module_as_converged():
    adjuster = DynamicBudgetAdjuster(predicted_budget=8)
    monitor = TrajectoryMonitor(plateau_window=3)
    decision = None
    for f in [6, 5, 5, 5, 5, 5]:
        status = monitor.observe(f)
        decision = adjuster.decide(status)
    assert decision == BudgetDecision.ESCALATE_EARLY


# ---------------------------------------------------------------------------
# Simulator: ground-truth consistency
# ---------------------------------------------------------------------------

def test_simulated_trajectory_never_reports_convergence_before_true_iteration():
    """Regression test: injected noise must never round a failure count to 0
    earlier than the trajectory's own declared true_convergence_iteration."""
    import random
    rng = random.Random(123)
    features = ModuleFeatures(embedded_sql=True, cics_handler=True, cyclomatic_complexity=20.0, dependency_count=8)
    for _ in range(200):
        traj = generate_trajectory(rng, "m", features)
        if traj.convergeable:
            zero_indices = [i for i, f in enumerate(traj.failure_counts, start=1) if f == 0]
            if zero_indices:
                assert min(zero_indices) == traj.true_convergence_iteration


def test_generate_trajectory_dataset_reproducible_with_seed():
    a = generate_trajectory_dataset(50, seed=99)
    b = generate_trajectory_dataset(50, seed=99)
    assert [t.true_convergence_iteration for t in a] == [t.true_convergence_iteration for t in b]


# ---------------------------------------------------------------------------
# Predictor
# ---------------------------------------------------------------------------

def test_predictor_falls_back_to_heuristic_before_training():
    predictor = IterationBudgetPredictor()
    simple = ModuleFeatures(embedded_sql=False, cics_handler=False, cyclomatic_complexity=5.0, dependency_count=1)
    complex_ = ModuleFeatures(embedded_sql=True, cics_handler=True, cyclomatic_complexity=20.0, dependency_count=10)
    assert predictor.is_trained is False
    assert predictor.predict(complex_) > predictor.predict(simple)


def test_predictor_learns_higher_budgets_for_embedded_sql_and_cics():
    dataset = generate_trajectory_dataset(800, seed=5)
    features = [t.features for t in dataset]
    targets = [t.true_convergence_iteration if t.convergeable else len(t.failure_counts) for t in dataset]
    predictor = IterationBudgetPredictor()
    predictor.fit(features, targets)
    assert predictor.is_trained

    simple = ModuleFeatures(embedded_sql=False, cics_handler=False, cyclomatic_complexity=4.0, dependency_count=1)
    complex_ = ModuleFeatures(embedded_sql=True, cics_handler=True, cyclomatic_complexity=15.0, dependency_count=6)
    assert predictor.predict(complex_) > predictor.predict(simple)


# ---------------------------------------------------------------------------
# End-to-end evaluation harness
# ---------------------------------------------------------------------------

def test_run_fixed_budget_converges_within_budget_when_possible():
    import random
    rng = random.Random(1)
    features = ModuleFeatures(embedded_sql=False, cics_handler=False, cyclomatic_complexity=3.0, dependency_count=1)
    traj = generate_trajectory(rng, "m", features)
    result = _run_fixed_budget(traj, budget=20)
    if traj.convergeable:
        assert result.outcome == "CONVERGED"
        assert result.iterations_used == traj.true_convergence_iteration


def test_refine_rl_never_exceeds_a_reasonable_hard_cap():
    import random
    rng = random.Random(2)
    features = ModuleFeatures(embedded_sql=True, cics_handler=True, cyclomatic_complexity=25.0, dependency_count=10)
    traj = generate_trajectory(rng, "m", features)
    predictor = IterationBudgetPredictor()
    result = _run_refine_rl(traj, predictor)
    assert result.iterations_used <= 20


def test_evaluation_harness_runs_end_to_end(tmp_path):
    summary, low, high, rl = run_evaluation(n_train=200, n_holdout=100, output_dir=Path(tmp_path))
    assert summary["predictor_trained"] is True
    assert len(low) == 100 and len(high) == 100 and len(rl) == 100
    # sanity: fixed-high should never converge less often than fixed-low on the same modules
    assert summary["fixed_high"]["convergence_rate"] >= summary["fixed_low"]["convergence_rate"]
