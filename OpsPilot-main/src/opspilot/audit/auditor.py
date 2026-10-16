"""Core audit engine and report models for OpsPilot."""

import ast
import json
import re
import importlib
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


class AuditSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class AuditFinding:
    check_id: str
    category: str
    severity: AuditSeverity
    title: str
    description: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    remediation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "category": self.category,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "remediation": self.remediation
        }


@dataclass
class AuditReport:
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    warning_count: int = 0
    error_count: int = 0
    critical_count: int = 0
    findings: List[AuditFinding] = field(default_factory=list)

    @property
    def has_faults(self) -> bool:
        return self.error_count > 0 or self.critical_count > 0

    def add_finding(self, finding: AuditFinding):
        self.findings.append(finding)
        if finding.severity == AuditSeverity.WARNING:
            self.warning_count += 1
        elif finding.severity == AuditSeverity.ERROR:
            self.error_count += 1
            self.failed_checks += 1
        elif finding.severity == AuditSeverity.CRITICAL:
            self.critical_count += 1
            self.failed_checks += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "critical_count": self.critical_count,
            "has_faults": self.has_faults,
            "findings": [f.to_dict() for f in self.findings]
        }

    def summary_text(self) -> str:
        lines = [
            "=" * 70,
            f" OpsPilot Audit Report - {self.timestamp}",
            "=" * 70,
            f"Total Checks Executed : {self.total_checks}",
            f"Passed Checks         : {self.passed_checks}",
            f"Failed / Fault Checks : {self.failed_checks}",
            f"  - Critical Faults   : {self.critical_count}",
            f"  - Errors            : {self.error_count}",
            f"  - Warnings          : {self.warning_count}",
            f"Overall Status        : {'FAILED (Faults Detected)' if self.has_faults else 'PASSED (Clean)'}",
            "-" * 70
        ]

        if not self.findings:
            lines.append("No faults or warnings identified. System conforms to all constraints.")
        else:
            lines.append("Detected Findings:")
            for idx, finding in enumerate(self.findings, 1):
                loc = f" [{finding.file_path}:{finding.line_number}]" if finding.file_path and finding.line_number else ""
                lines.append(f"\n{idx}. [{finding.severity.value}] {finding.check_id}: {finding.title}{loc}")
                lines.append(f"   Description : {finding.description}")
                if finding.remediation:
                    lines.append(f"   Remediation : {finding.remediation}")

        lines.append("=" * 70)
        return "\n".join(lines)


class OpsPilotAuditor:
    """Automated audit runner validating architectural, security, parser, and runtime constraints."""

    def __init__(self, root_dir: Optional[Path] = None):
        if root_dir is None:
            # Locate root directory relative to current file or working directory
            candidate = Path(__file__).resolve().parent.parent.parent.parent
            if (candidate / "src" / "opspilot").exists():
                self.root_dir = candidate
            else:
                self.root_dir = Path.cwd()
        else:
            self.root_dir = root_dir

        self.src_dir = self.root_dir / "src" / "opspilot"
        self.tests_dir = self.root_dir / "tests"

    def run_all_audits(self) -> AuditReport:
        """Executes all audit categories and returns consolidated report."""
        report = AuditReport()

        self.audit_architectural_constraints(report)
        self.audit_static_code_health(report)
        self.audit_security_guardrails(report)
        self.audit_parsers_and_data_contracts(report)
        self.audit_runtime_state_invariants(report)

        # Update passed checks count
        report.passed_checks = max(0, report.total_checks - report.failed_checks)
        return report

    def audit_architectural_constraints(self, report: AuditReport):
        """Audits the 4 Non-Negotiable Constraints in ARCHITECTURE.md."""
        # --- Check C1: Deterministic Static Analysis (No raw code to LLM for AST parsing) ---
        report.total_checks += 1
        analysis_agent_file = self.src_dir / "analysis" / "analysis_agent.py"
        if analysis_agent_file.exists():
            content = analysis_agent_file.read_text(encoding="utf-8")
            if "parse the AST" in content.lower() or "extract the ast" in content.lower():
                report.add_finding(AuditFinding(
                    check_id="ARCH-C1-001",
                    category="ARCHITECTURAL_CONSTRAINTS",
                    severity=AuditSeverity.CRITICAL,
                    title="Analysis Agent Prompt Violates Constraint 1",
                    description="Analysis agent prompt appears to request LLM to perform AST extraction directly.",
                    file_path=str(analysis_agent_file.relative_to(self.root_dir)),
                    remediation="Ensure AnalysisAgent only receives pre-parsed JSON summaries, not raw source for AST parsing."
                ))
            if "Do NOT write target code" not in content:
                report.add_finding(AuditFinding(
                    check_id="ARCH-C1-002",
                    category="ARCHITECTURAL_CONSTRAINTS",
                    severity=AuditSeverity.WARNING,
                    title="Missing Scope Boundary Guard in Analysis Agent",
                    description="Analysis agent prompt lacks explicit instruction forbidding direct target code generation.",
                    file_path=str(analysis_agent_file.relative_to(self.root_dir)),
                    remediation="Include 'Do NOT write target code' in AnalysisAgent system prompt."
                ))

        # --- Check C2: No Flat Multi-Agent Rooms ---
        report.total_checks += 1
        gc_token = "Group" + "Chat"
        gcm_token = "Group" + "ChatManager"
        forbidden_tokens = (gc_token, gcm_token)
        groupchat_found = []
        for py_file in self.src_dir.rglob("*.py"):
            if "audit" in py_file.parts:
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        for alias in node.names:
                            if alias.name in forbidden_tokens:
                                groupchat_found.append((py_file, node.lineno, f"from {node.module or ''} import {alias.name}"))
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if any(t in alias.name for t in forbidden_tokens):
                                groupchat_found.append((py_file, node.lineno, f"import {alias.name}"))
                    elif isinstance(node, ast.Name) and node.id in forbidden_tokens:
                        if isinstance(node.ctx, (ast.Load, ast.Store)):
                            groupchat_found.append((py_file, node.lineno, f"Active symbol reference '{node.id}'"))
            except Exception:
                pass

        if groupchat_found:
            for fpath, lnum, ltxt in groupchat_found:
                report.add_finding(AuditFinding(
                    check_id="ARCH-C2-001",
                    category="ARCHITECTURAL_CONSTRAINTS",
                    severity=AuditSeverity.CRITICAL,
                    title="Flat Conversation Room Detected (Constraint 2 Violation)",
                    description=f"Prohibited {gc_token} structure detected: '{ltxt}'",
                    file_path=str(fpath.relative_to(self.root_dir) if fpath.is_relative_to(self.root_dir) else fpath),
                    line_number=lnum,
                    remediation="Replace room with sequential Python control plane via UserProxyAgent / initiate_chat."
                ))

        # --- Check C3: Strict Inner Loop Isolation ---
        report.total_checks += 1
        self_refine_file = self.src_dir / "execution" / "self_refine_loop.py"
        if self_refine_file.exists():
            code = self_refine_file.read_text(encoding="utf-8")
            if "AnalysisAgent" in code or "GuardrailAgent" in code:
                report.add_finding(AuditFinding(
                    check_id="ARCH-C3-001",
                    category="ARCHITECTURAL_CONSTRAINTS",
                    severity=AuditSeverity.CRITICAL,
                    title="Inner Loop Polluted by Third-Party Agent (Constraint 3 Violation)",
                    description="Phase 3 self-refinement loop imports or references AnalysisAgent or GuardrailAgent.",
                    file_path=str(self_refine_file.relative_to(self.root_dir)),
                    remediation="Ensure only Coder and Verifier participate in the inner self-refine loop."
                ))
            if "max_turns" not in code or "budget_exhausted" not in code:
                report.add_finding(AuditFinding(
                    check_id="ARCH-C3-002",
                    category="ARCHITECTURAL_CONSTRAINTS",
                    severity=AuditSeverity.ERROR,
                    title="Missing Bounded Turn Budget Enforcement in Self-Refine Loop",
                    description="The self-refinement loop must strictly bound turns and handle budget exhaustion.",
                    file_path=str(self_refine_file.relative_to(self.root_dir)),
                    remediation="Enforce max_turns parameter and return explicit budget_exhausted flag."
                ))

        # --- Check C4: Deterministic Guardrail Interceptors at position=0 ---
        report.total_checks += 1
        interceptor_file = self.src_dir / "governance" / "guardrail_interceptor.py"
        if interceptor_file.exists():
            code = interceptor_file.read_text(encoding="utf-8")
            if "position=0" not in code:
                report.add_finding(AuditFinding(
                    check_id="ARCH-C4-001",
                    category="ARCHITECTURAL_CONSTRAINTS",
                    severity=AuditSeverity.CRITICAL,
                    title="Guardrail Interceptor Not Registered at Position 0 (Constraint 4 Violation)",
                    description="Guardrail interceptor registration does not specify position=0 priority.",
                    file_path=str(interceptor_file.relative_to(self.root_dir)),
                    remediation="Register interceptor with position=0 so it evaluates prior to code execution or LLM handlers."
                ))

    def audit_static_code_health(self, report: AuditReport):
        """Audits AST parsing syntax, broken syntax, and structural code health."""
        report.total_checks += 1
        for py_file in self.src_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                ast.parse(content, filename=str(py_file))
            except SyntaxError as se:
                report.add_finding(AuditFinding(
                    check_id="STATIC-001",
                    category="STATIC_CODE_HEALTH",
                    severity=AuditSeverity.CRITICAL,
                    title="Python Syntax Error",
                    description=f"Syntax error during AST parse: {se.msg}",
                    file_path=str(py_file.relative_to(self.root_dir)),
                    line_number=se.lineno,
                    remediation="Fix Python syntax error."
                ))
            except Exception as ex:
                report.add_finding(AuditFinding(
                    check_id="STATIC-002",
                    category="STATIC_CODE_HEALTH",
                    severity=AuditSeverity.ERROR,
                    title="AST Parse Exception",
                    description=f"Failed to parse file: {str(ex)}",
                    file_path=str(py_file.relative_to(self.root_dir)),
                    remediation="Ensure file has valid Python encoding and structure."
                ))

    def audit_security_guardrails(self, report: AuditReport):
        """Audits regex pattern compilation and coverage in guardrail rules."""
        report.total_checks += 1
        try:
            from opspilot.governance.guardrail_rules import get_all_prohibited_rules
            rules = get_all_prohibited_rules()
            if len(rules) < 7:
                report.add_finding(AuditFinding(
                    check_id="SEC-001",
                    category="SECURITY_GUARDRAILS",
                    severity=AuditSeverity.ERROR,
                    title="Insufficient Guardrail Rules",
                    description=f"Found only {len(rules)} safety rules; expected at least 7.",
                    file_path="src/opspilot/governance/guardrail_rules.py",
                    remediation="Add required rules for JVM termination, OS execution, SQL DDL/injection, credentials."
                ))

            # Verify pattern compilation and test vectors
            for rule in rules:
                rid = rule.get("id", "UNKNOWN")
                pattern = rule.get("pattern", "")
                is_regex = rule.get("is_regex", False)

                if is_regex:
                    try:
                        compiled = re.compile(pattern, re.IGNORECASE)
                    except re.error as re_err:
                        report.add_finding(AuditFinding(
                            check_id="SEC-002",
                            category="SECURITY_GUARDRAILS",
                            severity=AuditSeverity.CRITICAL,
                            title=f"Invalid Guardrail Regex Pattern in {rid}",
                            description=f"Regex compilation error: {str(re_err)}",
                            file_path="src/opspilot/governance/guardrail_rules.py",
                            remediation=f"Correct regex pattern for rule {rid}."
                        ))

            # Test SQL injection coverage: verify INSERT/UPDATE/DELETE concatenation coverage
            sql_rule = next((r for r in rules if r.get("id") == "RULE_RAW_JDBC_CONCAT"), None)
            if sql_rule:
                compiled = re.compile(sql_rule["pattern"], re.IGNORECASE)
                insert_test = "INSERT INTO users VALUES ('a' + userVar)"
                if not compiled.search(insert_test):
                    report.add_finding(AuditFinding(
                        check_id="SEC-003",
                        category="SECURITY_GUARDRAILS",
                        severity=AuditSeverity.WARNING,
                        title="SQL Injection Guardrail Incomplete Coverage",
                        description="RULE_RAW_JDBC_CONCAT pattern catches SELECT statements but misses INSERT/UPDATE/DELETE concatenation.",
                        file_path="src/opspilot/governance/guardrail_rules.py",
                        remediation="Broaden SQL injection regex to include SELECT, INSERT, UPDATE, DELETE concatenation."
                    ))

        except Exception as ex:
            report.add_finding(AuditFinding(
                check_id="SEC-000",
                category="SECURITY_GUARDRAILS",
                severity=AuditSeverity.ERROR,
                title="Failed to Load Guardrail Rules",
                description=str(ex),
                file_path="src/opspilot/governance/guardrail_rules.py"
            ))

    def audit_parsers_and_data_contracts(self, report: AuditReport):
        """Audits COBOL and PL/SQL parser outputs against sample legacy files."""
        report.total_checks += 1
        payroll_file = self.root_dir / "examples" / "sample_legacy" / "PAYROLL.CBL"
        orders_file = self.root_dir / "examples" / "sample_legacy" / "ORDERS.SQL"

        from opspilot.analysis.parsers.cobol_parser import parse_cobol_file
        from opspilot.analysis.parsers.plsql_parser import parse_plsql_file
        from opspilot.utils.json_schema import validate_analysis_output

        # Audit COBOL parsing
        if payroll_file.exists():
            try:
                cobol_res = parse_cobol_file(payroll_file)
                valid, err = validate_analysis_output(cobol_res)
                if not valid:
                    report.add_finding(AuditFinding(
                        check_id="PARSE-CBL-001",
                        category="PARSERS_AND_SCHEMA",
                        severity=AuditSeverity.ERROR,
                        title="COBOL Parser Output Schema Violation",
                        description=f"PAYROLL.CBL output failed schema validation: {err}",
                        file_path=str(payroll_file.relative_to(self.root_dir)),
                        remediation="Update cobol_parser to output all required schema fields."
                    ))
                if not cobol_res.get("sections_or_procedures"):
                    report.add_finding(AuditFinding(
                        check_id="PARSE-CBL-002",
                        category="PARSERS_AND_SCHEMA",
                        severity=AuditSeverity.ERROR,
                        title="COBOL Parser Found No Paragraphs/Sections",
                        description="Parsed PAYROLL.CBL but extracted 0 procedures/paragraphs.",
                        file_path=str(payroll_file.relative_to(self.root_dir)),
                        remediation="Ensure PROCEDURE DIVISION paragraph regex handles valid labels."
                    ))
            except Exception as ex:
                report.add_finding(AuditFinding(
                    check_id="PARSE-CBL-EX",
                    category="PARSERS_AND_SCHEMA",
                    severity=AuditSeverity.CRITICAL,
                    title="COBOL Parser Crashed on Sample Source",
                    description=str(ex),
                    file_path=str(payroll_file.relative_to(self.root_dir))
                ))

        # Audit PL/SQL parsing
        if orders_file.exists():
            try:
                plsql_res = parse_plsql_file(orders_file)
                valid, err = validate_analysis_output(plsql_res)
                if not valid:
                    report.add_finding(AuditFinding(
                        check_id="PARSE-SQL-001",
                        category="PARSERS_AND_SCHEMA",
                        severity=AuditSeverity.ERROR,
                        title="PL/SQL Parser Output Schema Violation",
                        description=f"ORDERS.SQL output failed schema validation: {err}",
                        file_path=str(orders_file.relative_to(self.root_dir)),
                        remediation="Update plsql_parser to conform to ANALYSIS_OUTPUT_SCHEMA."
                    ))
                # Check call/parameter field sanity
                for proc in plsql_res.get("sections_or_procedures", []):
                    # Check if 'calls' mistakenly holds type definitions like 'IN NUMBER'
                    for c in proc.get("calls", []):
                        if " IN " in f" {c} " or " OUT " in f" {c} ":
                            report.add_finding(AuditFinding(
                                check_id="PARSE-SQL-002",
                                category="PARSERS_AND_SCHEMA",
                                severity=AuditSeverity.WARNING,
                                title="PL/SQL Parser Confuses Parameters with Calls",
                                description=f"Procedure '{proc['name']}' has parameter definition '{c}' in calls field.",
                                file_path="src/opspilot/analysis/parsers/plsql_parser.py",
                                remediation="Store calls as procedure invocations, not procedure parameter signatures."
                            ))
                            break
            except Exception as ex:
                report.add_finding(AuditFinding(
                    check_id="PARSE-SQL-EX",
                    category="PARSERS_AND_SCHEMA",
                    severity=AuditSeverity.CRITICAL,
                    title="PL/SQL Parser Crashed on Sample Source",
                    description=str(ex),
                    file_path=str(orders_file.relative_to(self.root_dir))
                ))

    def audit_runtime_state_invariants(self, report: AuditReport):
        """Audits state lifecycle, end_time recording, guardrail logs, and verifier reports."""
        report.total_checks += 1
        orchestrator_file = self.src_dir / "orchestration" / "master_orchestrator.py"
        if orchestrator_file.exists():
            code = orchestrator_file.read_text(encoding="utf-8")
            if "state.end_time" not in code:
                report.add_finding(AuditFinding(
                    check_id="RUNTIME-001",
                    category="RUNTIME_STATE_INVARIANTS",
                    severity=AuditSeverity.ERROR,
                    title="Pipeline Execution Never Populates state.end_time",
                    description="PipelineState defines end_time, but master_orchestrator never sets state.end_time upon completion or failure.",
                    file_path="src/opspilot/orchestration/master_orchestrator.py",
                    remediation="Set state.end_time = datetime.now().isoformat() in both success and failure branches."
                ))
            if "state.guardrail_logs" not in code or "guardrail_log.json" not in code:
                report.add_finding(AuditFinding(
                    check_id="RUNTIME-002",
                    category="RUNTIME_STATE_INVARIANTS",
                    severity=AuditSeverity.WARNING,
                    title="Pipeline Does Not Populate state.guardrail_logs On Violation",
                    description="When a guardrail violation is detected, state.guardrail_logs is not populated with the audit log entry.",
                    file_path="src/opspilot/orchestration/master_orchestrator.py",
                    remediation="Load written guardrail_log.json events into state.guardrail_logs on violation."
                ))

        # Check self_refine_loop verifier report timestamp
        self_refine_file = self.src_dir / "execution" / "self_refine_loop.py"
        if self_refine_file.exists():
            code = self_refine_file.read_text(encoding="utf-8")
            if '"timestamp": ""' in code or "'timestamp': ''" in code:
                report.add_finding(AuditFinding(
                    check_id="RUNTIME-003",
                    category="RUNTIME_STATE_INVARIANTS",
                    severity=AuditSeverity.WARNING,
                    title="Empty Timestamp in Verifier Report",
                    description="Verifier report emits an empty string for required timestamp field.",
                    file_path="src/opspilot/execution/self_refine_loop.py",
                    remediation="Populate verifier_report['timestamp'] with datetime.now().isoformat()."
                ))
