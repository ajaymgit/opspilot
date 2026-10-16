"""Phase 3 Verifier Agent wrapper.

Executes and verifies generated Java code within a sandboxed workspace (Docker / local fallback).
Evaluates compilation and tests, returning structured logs to the Coder.
"""

from typing import Dict, Any, Optional
from autogen import UserProxyAgent


def is_verifier_termination(msg: Optional[Dict[str, Any]]) -> bool:
    """Evaluates whether message signals execution loop termination."""
    if not msg or not isinstance(msg, dict):
        return False
    content = msg.get("content", "")
    if isinstance(content, str):
        return "TERMINATE" in content or "BUILD SUCCESS" in content
    return False


def create_verifier_agent(sandbox_config: Optional[Dict[str, Any]] = None) -> UserProxyAgent:
    """Instantiates the Verifier UserProxyAgent with sandboxed execution configuration."""
    if sandbox_config is None:
        sandbox_config = {"work_dir": "workspace", "use_docker": False}

    work_dir = sandbox_config.get("work_dir", "workspace")
    use_docker = sandbox_config.get("use_docker", False)

    return UserProxyAgent(
        name="Verifier",
        human_input_mode="NEVER",
        code_execution_config={
            "work_dir": work_dir,
            "use_docker": use_docker
        },
        is_termination_msg=is_verifier_termination
    )
