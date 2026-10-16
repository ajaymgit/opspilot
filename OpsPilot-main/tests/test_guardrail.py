"""Unit tests for Phase 4 Governance Layer and Deterministic Guardrails."""

import json
from pathlib import Path
import pytest
from autogen import AssistantAgent, UserProxyAgent

from opspilot.governance.guardrail_rules import get_all_prohibited_rules
from opspilot.governance.guardrail_interceptor import (
    deterministic_guardrail_check,
    register_guardrail_interceptor
)


@pytest.fixture
def mock_agents():
    verifier = UserProxyAgent("Verifier", human_input_mode="NEVER", code_execution_config=False)
    coder = AssistantAgent("Coder", llm_config={"model": "gpt-4o"})
    return verifier, coder


def test_clean_message_passes(mock_agents):
    verifier, coder = mock_agents
    messages = [{"content": "public class CleanService { public void run() {} }"}]

    triggered, reason = deterministic_guardrail_check(verifier, messages, coder)
    assert triggered is False
    assert reason is None


def test_individual_prohibited_patterns(mock_agents, tmp_path):
    verifier, coder = mock_agents
    log_file = tmp_path / "guardrail_log.json"
    config = {"log_path": str(log_file)}

    forbidden_payloads = [
        ("System.exit", "RULE_SYSTEM_EXIT"),
        ("Runtime.getRuntime().exec", "RULE_RUNTIME_EXEC"),
        ("ProcessBuilder", "RULE_PROCESS_BUILDER"),
        ("DROP TABLE", "RULE_SQL_DROP"),
        ("rm -rf", "RULE_UNLINK_ALL"),
        ("SELECT * FROM users + userInput", "RULE_RAW_JDBC_CONCAT"),
        ('password = "mySecretPassword123"', "RULE_HARDCODED_PASSWORD"),
    ]

    for payload, expected_rule in forbidden_payloads:
        messages = [{"content": f"// Valid comment\n{payload}\n"}]
        triggered, reason = deterministic_guardrail_check(verifier, messages, coder, config=config)

        assert triggered is True, f"Failed to trigger guardrail for: {payload}"
        assert "GUARDRAIL_VIOLATION" in reason
        assert expected_rule in reason, f"Expected rule {expected_rule} in {reason}"


def test_embedded_pattern_detection(mock_agents, tmp_path):
    """Confirm guardrail triggers even when embedded inside complex valid Java source code."""
    verifier, coder = mock_agents
    log_file = tmp_path / "guardrail_log.json"
    config = {"log_path": str(log_file)}

    complex_java_code = """
    package com.example.service;

    import org.springframework.stereotype.Service;

    @Service
    public class OrderService {
        public void executeEmergencyShutdown() {
            System.out.println("Stopping service...");
            System.exit(1); // EMBEDDED VIOLATION HERE
        }
    }
    """
    messages = [{"content": complex_java_code}]
    triggered, reason = deterministic_guardrail_check(verifier, messages, coder, config=config)

    assert triggered is True
    assert "RULE_SYSTEM_EXIT" in reason


def test_position_zero_interceptor_registration(mock_agents, tmp_path):
    """Verify position=0 registration on Verifier agent."""
    verifier, coder = mock_agents
    log_file = tmp_path / "guardrail_log.json"

    register_guardrail_interceptor(verifier, guardrail_log_path=log_file)

    # Check registered reply functions on verifier
    # AutoGen stores registered replies in _reply_func_list
    assert len(verifier._reply_func_list) > 0
    first_handler = verifier._reply_func_list[0]
    assert first_handler["reply_func"] == deterministic_guardrail_check


def test_guardrail_violation_logging(mock_agents, tmp_path):
    """Verify violation event is appended to guardrail_log.json with required fields."""
    verifier, coder = mock_agents
    log_file = tmp_path / "guardrail_log.json"
    config = {"log_path": str(log_file)}

    messages = [{"content": "rm -rf /tmp/data"}]
    triggered, reason = deterministic_guardrail_check(verifier, messages, coder, config=config)

    assert triggered is True
    assert log_file.exists()

    with open(log_file, "r", encoding="utf-8") as f:
        logs = json.load(f)

    assert len(logs) == 1
    event = logs[0]
    assert event["matched_rule"] == "RULE_UNLINK_ALL"
    assert event["pattern"] == "rm -rf"
    assert "offending_message" in event
    assert "timestamp" in event
    assert "pipeline_stage" in event


def test_interceptor_fires_before_code_execution_for_all_denylisted_rules(tmp_path):
    """Explicitly test Criterion 4: Guardrail interception provably fires BEFORE code execution for every denylisted rule."""
    rules = get_all_prohibited_rules()
    assert len(rules) >= 7, "Expected at least 7 denylisted safety rules"

    for rule in rules:
        verifier = UserProxyAgent("Verifier", human_input_mode="NEVER", code_execution_config=False)
        coder = AssistantAgent("Coder", llm_config={"model": "gpt-4o"})
        log_file = tmp_path / f"guardrail_log_{rule['id']}.json"

        # Track whether secondary execution handler was ever called
        execution_occurred = []

        def mock_code_execution_handler(recipient, messages, sender, config):
            execution_occurred.append(True)
            return False, "Executed code side-effect"

        # Register position=0 guardrail interceptor
        register_guardrail_interceptor(verifier, guardrail_log_path=log_file)

        # Register secondary position=1 execution handler
        verifier.register_reply(trigger=AssistantAgent, reply_func=mock_code_execution_handler, position=1)

        # Construct forbidden test message for this rule
        payload = rule["pattern"]
        if rule.get("is_regex", False):
            if "SELECT" in payload:
                forbidden_text = "SELECT * FROM users + inputVar"
            elif "password" in payload:
                forbidden_text = 'password = "SecretPassword123"'
            else:
                forbidden_text = payload
        else:
            forbidden_text = f"// Code sample\n{payload}\n"

        # Trigger chat message processing
        verifier.initiate_chat(coder, message=forbidden_text, max_turns=1)

        # Assert: Guardrail fired, logged, and secondary code execution handler WAS NEVER CALLED
        chat_msgs = verifier.chat_messages[coder]
        last_msg = chat_msgs[-1]["content"]

        assert "GUARDRAIL_VIOLATION" in last_msg, f"Guardrail failed to trigger for rule {rule['id']}"
        assert len(execution_occurred) == 0, f"PROVABILITY FAILURE: Code execution fired despite guardrail violation for rule {rule['id']}!"
        assert log_file.exists(), f"Guardrail log file was not created for rule {rule['id']}"

