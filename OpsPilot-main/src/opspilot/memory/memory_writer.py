"""MemoryWriter: after a module passes Verification (Phase 3) and Governance
(Phase 4), records it into both RepoMind stores in one call -- the dependency
graph (for future change propagation) and semantic memory (for future
rationale recall). This is the integration point Phase 3/4 code calls; it does
not itself decide what counts as noteworthy, it just persists what it's given.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from opspilot.memory.repo_dependency_graph import RepoDependencyGraph
from opspilot.memory.semantic_memory import DecisionEntry, SemanticMemory


class MemoryWriter:
    def __init__(self, repo_graph: RepoDependencyGraph, semantic_memory: SemanticMemory):
        self.repo_graph = repo_graph
        self.semantic_memory = semantic_memory

    def record_verified_module(
        self,
        module_id: str,
        module_graph_dict: Optional[Dict[str, Any]] = None,
        rationale: str = "",
        edge_cases: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        if module_graph_dict:
            self.repo_graph.ingest_module_graph(module_graph_dict)

        if rationale or edge_cases:
            entry = DecisionEntry(
                entry_id=f"{module_id}-{len(self.semantic_memory.entries)}",
                module_id=module_id,
                rationale=rationale,
                edge_cases=edge_cases or [],
                tags=tags or [],
            )
            self.semantic_memory.write(entry)
