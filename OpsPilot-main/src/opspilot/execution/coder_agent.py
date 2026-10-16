"""Phase 3 Coder Agent wrapper.

Translates modern OO design specifications into production-grade Java microservices.
On refinement turns, strictly fixes ONLY the reported compiler or test errors.
"""

from typing import Dict, Any
from autogen import AssistantAgent

CODER_AGENT_SYSTEM_PROMPT = """You are an Expert Java Microservices Developer.
Your task is to translate the provided legacy logic specs and OO class design into modern Java Spring Boot microservices.

Rules:
1. Output valid, complete Java source files (e.g. ```java ... ```).
2. Follow standard Spring Boot patterns (@RestController, @Service, @Repository, @Entity, DTOs).
3. If the Verifier returns error logs or test failures, fix ONLY the reported errors and return the revised code. Do NOT rewrite working, unrelated classes.
4. Conclude your submission with standard Java microservice code blocks.
"""


def create_coder_agent(llm_config: Dict[str, Any]) -> AssistantAgent:
    """Instantiates the Coder AssistantAgent."""
    return AssistantAgent(
        name="Coder",
        llm_config=llm_config,
        system_message=CODER_AGENT_SYSTEM_PROMPT
    )
