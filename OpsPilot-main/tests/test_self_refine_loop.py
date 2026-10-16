"""Unit tests for Phase 3 Autonomous Self-Refine inner loop."""

from pathlib import Path
import pytest
from autogen import UserProxyAgent

from opspilot.execution.coder_agent import create_coder_agent
from opspilot.execution.verifier_agent import create_verifier_agent, is_verifier_termination
from opspilot.execution.self_refine_loop import run_self_refine_loop, extract_code_blocks


def test_is_verifier_termination_lambda():
    assert is_verifier_termination({"content": "BUILD SUCCESS - 10 tests passed."}) is True
    assert is_verifier_termination({"content": "Process finished with TERMINATE code."}) is True
    assert is_verifier_termination({"content": "Compilation error on line 42."}) is False
    assert is_verifier_termination(None) is False


def test_extract_code_blocks():
    sample_text = """
    Here is the Spring Boot service:
    ```java
    package com.example;
    public class OrderService {
        public void processOrder() {}
    }
    ```
    """
    blocks = extract_code_blocks(sample_text)
    assert "OrderService.java" in blocks
    assert "public class OrderService" in blocks["OrderService.java"]


def test_self_refine_loop_isolation():
    llm_config = {"model": "gpt-4o"}
    coder = create_coder_agent(llm_config)
    verifier = create_verifier_agent({"work_dir": "workspace", "use_docker": False})
    orchestrator = UserProxyAgent("Orchestrator", human_input_mode="NEVER", code_execution_config=False)

    analysis_output = {"program_name": "PAYROLL", "sections_or_procedures": []}
    roadmap = "Sample OO Java Roadmap"

    # Test loop execution with budget B=2
    result = run_self_refine_loop(
        orchestrator_agent=orchestrator,
        coder_agent=coder,
        verifier_agent=verifier,
        design_roadmap=roadmap,
        analysis_output=analysis_output,
        max_turns=2
    )

    assert "turns_used" in result
    assert result["turns_used"] <= 2
    assert "generated_code" in result
    assert "verifier_report" in result


def test_deliberately_unfixable_spec_budget_exhaustion():
    """Explicitly test Criterion 3: Unfixable spec terminates at max_turns budget B with budget_exhausted=True."""
    llm_config = {"model": "gpt-4o"}
    coder = create_coder_agent(llm_config)
    verifier = create_verifier_agent({"work_dir": "workspace", "use_docker": False})
    orchestrator = UserProxyAgent("Orchestrator", human_input_mode="NEVER", code_execution_config=False)

    # Mock custom response generator on verifier that simulates continuous compilation failure
    def mock_failing_response(recipient, history):
        return "COMPILATION ERROR: Syntax error on line 1. Cannot compile."

    verifier._generate_response = mock_failing_response

    analysis_output = {"program_name": "UNFIXABLE_PROGRAM", "sections_or_procedures": []}
    roadmap = "Unfixable Specification Roadmap"
    budget_limit = 4

    result = run_self_refine_loop(
        orchestrator_agent=orchestrator,
        coder_agent=coder,
        verifier_agent=verifier,
        design_roadmap=roadmap,
        analysis_output=analysis_output,
        max_turns=budget_limit
    )

    # Assert strict budget termination
    assert result["turns_used"] == budget_limit, f"Expected exactly {budget_limit} turns, got {result['turns_used']}"
    assert result["budget_exhausted"] is True, "Expected budget_exhausted to be True"
    assert result["success"] is False, "Expected success to be False"
    assert result["verifier_report"]["build_success"] is False, "Expected build_success to be False"

