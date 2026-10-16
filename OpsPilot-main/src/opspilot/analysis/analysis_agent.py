"""Phase 1 Analysis Agent wrapper.

The Analysis Agent takes pre-parsed AST summaries and JSON dependency trees
and generates a modern Object-Oriented class design and microservice architecture
roadmap. System prompt explicitly forbids writing target code.
"""

from typing import Dict, Any
from autogen import AssistantAgent


ANALYSIS_AGENT_SYSTEM_PROMPT = """You are a Legacy Code Analyst. You take pre-parsed AST summaries
and JSON dependency trees of legacy code (COBOL/PL-SQL) and map out the modern OO
class design and business logic roadmap. Do NOT write target code.

Your response MUST specify:
1. Modern Java Class Entities & DTOs corresponding to DATA DIVISION / CURSOR layouts.
2. Spring Boot Service & Repository architectural breakdown.
3. Step-by-step business logic migration plan based on the call graph / PERFORM chain.
4. Data validation and transactional boundaries.
"""


def create_analysis_agent(llm_config: Dict[str, Any]) -> AssistantAgent:
    """Instantiates the isolated AnalysisAgent."""
    return AssistantAgent(
        name="AnalysisAgent",
        llm_config=llm_config,
        system_message=ANALYSIS_AGENT_SYSTEM_PROMPT
    )
