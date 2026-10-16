"""Unit tests for Phase 2 Master Orchestration and Control Plane."""

from pathlib import Path
import pytest

from opspilot.orchestration.master_orchestrator import MasterOrchestrator, run_pipeline
from opspilot.orchestration.pipeline_state import PipelineState


def test_no_groupchat_in_codebase():
    """Repo-wide lint check: Enforce Constraint 2 (No GroupChat anywhere in src/)."""
    src_dir = Path("src")
    groupchat_occurrences = []

    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        # Check for active GroupChat usage (excluding comments if any)
        lines = content.splitlines()
        for idx, line in enumerate(lines, start=1):
            clean = line.strip()
            if "GroupChat" in clean and not clean.startswith("#"):
                groupchat_occurrences.append(f"{py_file}:{idx}: {clean}")

    assert len(groupchat_occurrences) == 0, (
        f"GroupChat detected in codebase! Constraint 2 violation:\n" + "\n".join(groupchat_occurrences)
    )


def test_master_orchestrator_execution(tmp_path):
    cobol_file = Path("examples/sample_legacy/PAYROLL.CBL")
    assert cobol_file.exists()

    orchestrator = MasterOrchestrator()
    result = orchestrator.run_pipeline(str(cobol_file))

    assert result.state.phase_status["phase1_analysis"] == "COMPLETED"
    assert result.state.phase_status["phase2_orchestration"] == "COMPLETED"
    assert "PAYROLL" in result.state.analysis_output["program_name"]

    # Confirm saved artifacts
    workspace = Path("workspace")
    assert (workspace / "analysis_output.json").exists()
    assert (workspace / "design_roadmap.md").exists()
    assert (workspace / "verifier_report.json").exists()
