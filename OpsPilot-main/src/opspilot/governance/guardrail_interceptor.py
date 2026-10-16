"""Deterministic Python safety guardrail interceptor for AutoGen agents.

Registers a position=0 reply interceptor on the Verifier agent to validate code
against hardcoded governance denylists before any LLM/tool processing or code execution occurs.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from autogen import AssistantAgent, UserProxyAgent

from opspilot.governance.guardrail_rules import get_all_prohibited_rules


def deterministic_guardrail_check(
    recipient: UserProxyAgent,
    messages: List[Dict[str, Any]],
    sender: AssistantAgent,
    config: Optional[Dict[str, Any]] = None
) -> Tuple[bool, Optional[str]]:
    """Deterministic validation function intercepting messages before execution.

    Signature compatible with AutoGen's register_reply.
    Position 0 guarantees execution prior to tools or default reply handlers.
    """
    if not messages:
        return False, None

    last_message = messages[-1].get("content", "")
    if not isinstance(last_message, str):
        return False, None

    rules = get_all_prohibited_rules()

    for rule in rules:
        matched = False
        pattern = rule["pattern"]
        if rule.get("is_regex", False):
            if re.search(pattern, last_message, re.IGNORECASE):
                matched = True
        else:
            if pattern in last_message:
                matched = True

        if matched:
            rule_id = rule["id"]
            desc = rule["description"]
            violation_msg = f"GUARDRAIL_VIOLATION: [{rule_id}] Prohibited pattern '{pattern}' detected ({desc}). Action aborted."

            # Log violation to JSON audit trail
            log_path = Path(config.get("log_path", "workspace/guardrail_log.json")) if config else Path("workspace/guardrail_log.json")
            log_guardrail_violation(
                rule_id=rule_id,
                matched_pattern=pattern,
                offending_content=last_message,
                log_path=log_path
            )

            return True, violation_msg

    return False, None


def log_guardrail_violation(rule_id: str, matched_pattern: str, offending_content: str, log_path: Path):
    """Logs guardrail violation event to JSON file."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now().isoformat(),
        "matched_rule": rule_id,
        "pattern": matched_pattern,
        "offending_message": offending_content[:500],
        "pipeline_stage": "Phase 4: Governance Guardrail Interceptor"
    }

    logs = []
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []

    logs.append(event)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2)


def register_guardrail_interceptor(verifier_agent: UserProxyAgent, guardrail_log_path: Optional[Path] = None):
    """Registers the deterministic check on Verifier at position=0."""
    verifier_agent.register_reply(
        trigger=AssistantAgent,
        reply_func=deterministic_guardrail_check,
        position=0,
        config={"log_path": str(guardrail_log_path or Path("workspace/guardrail_log.json"))}
    )
