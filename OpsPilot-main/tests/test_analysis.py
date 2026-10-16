"""Unit tests for Phase 1 Deterministic Analysis & AST Extraction layer."""

from pathlib import Path
import pytest

from opspilot.analysis.parsers.cobol_parser import parse_cobol_file
from opspilot.analysis.parsers.plsql_parser import parse_plsql_file
from opspilot.analysis.dependency_graph import DependencyGraphBuilder
from opspilot.analysis.analysis_agent import create_analysis_agent, ANALYSIS_AGENT_SYSTEM_PROMPT
from opspilot.utils.json_schema import validate_analysis_output


def test_cobol_parser():
    cobol_file = Path("examples/sample_legacy/PAYROLL.CBL")
    assert cobol_file.exists()

    analysis = parse_cobol_file(cobol_file)
    assert analysis["language"] == "COBOL"
    assert analysis["program_name"] == "PAYROLL"
    assert len(analysis["sections_or_procedures"]) > 0
    assert len(analysis["copybooks_or_includes"]) > 0
    assert "EMPREC.CPY" in analysis["copybooks_or_includes"]

    is_valid, err = validate_analysis_output(analysis)
    assert is_valid, f"Schema validation error: {err}"


def test_plsql_parser():
    sql_file = Path("examples/sample_legacy/ORDERS.SQL")
    assert sql_file.exists()

    analysis = parse_plsql_file(sql_file)
    assert analysis["language"] == "PLSQL"
    assert analysis["program_name"] == "ORDER_PROCESSOR"
    assert len(analysis["sections_or_procedures"]) > 0
    assert len(analysis["embedded_sql"]) > 0

    is_valid, err = validate_analysis_output(analysis)
    assert is_valid, f"Schema validation error: {err}"


def test_dependency_graph_builder():
    cobol_file = Path("examples/sample_legacy/PAYROLL.CBL")
    analysis = parse_cobol_file(cobol_file)

    builder = DependencyGraphBuilder(analysis)
    graph_dict = builder.to_dict()

    assert graph_dict["program"] == "PAYROLL"
    assert graph_dict["node_count"] > 0
    assert graph_dict["edge_count"] > 0

    order = builder.get_execution_order()
    assert len(order) > 0


def test_analysis_agent_system_prompt_constraint():
    """Verify Constraint 1/2 rule: Analysis Agent prompt strictly forbids writing target code."""
    agent = create_analysis_agent({"model": "gpt-4o"})
    assert "Do NOT write target code" in agent.system_message
    assert "Legacy Code Analyst" in agent.system_message
