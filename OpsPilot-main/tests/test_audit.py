"""Unit tests for the OpsPilot Automated Audit Subsystem."""

from pathlib import Path
from opspilot.audit.auditor import OpsPilotAuditor, AuditSeverity


def test_auditor_execution():
    """Verify that the auditor runs all check categories and produces a structured report."""
    auditor = OpsPilotAuditor()
    report = auditor.run_all_audits()

    assert report.total_checks >= 5
    assert report.passed_checks > 0
    assert not report.has_faults, f"Audit detected unresolved faults: {report.findings}"


def test_architectural_constraints_audit():
    """Verify that the codebase satisfies all 4 non-negotiable architectural constraints."""
    auditor = OpsPilotAuditor()
    report = auditor.run_all_audits()

    arch_findings = [f for f in report.findings if f.category == "ARCHITECTURAL_CONSTRAINTS" and f.severity in [AuditSeverity.ERROR, AuditSeverity.CRITICAL]]
    assert len(arch_findings) == 0, f"Architectural constraint violations detected: {arch_findings}"


def test_security_guardrails_audit():
    """Verify that all guardrail rules compile, cover SQL injection variants, and don't fail."""
    auditor = OpsPilotAuditor()
    report = auditor.run_all_audits()

    sec_findings = [f for f in report.findings if f.category == "SECURITY_GUARDRAILS" and f.severity in [AuditSeverity.ERROR, AuditSeverity.CRITICAL]]
    assert len(sec_findings) == 0, f"Security guardrail faults detected: {sec_findings}"


def test_runtime_state_invariants():
    """Verify that runtime state invariant checks succeed (e.g. state.end_time and report timestamps)."""
    auditor = OpsPilotAuditor()
    report = auditor.run_all_audits()

    runtime_findings = [f for f in report.findings if f.category == "RUNTIME_STATE_INVARIANTS" and f.severity in [AuditSeverity.ERROR, AuditSeverity.CRITICAL]]
    assert len(runtime_findings) == 0, f"Runtime invariant faults detected: {runtime_findings}"
