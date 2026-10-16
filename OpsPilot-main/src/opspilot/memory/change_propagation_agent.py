"""Change Propagation Agent: when a module or shared copybook changes, finds
every module that needs to be *re-verified* (not re-translated) as a result.

Deliberately conservative: `RepoDependencyGraph.structural_dependents` returns
every node that could possibly be affected (everything reachable backward
through COPY/CALL/uses edges), which by construction can never miss a module
that is genuinely impacted -- the trade-off, and it is an intentional one for
a governance-adjacent tool, is that some structurally-adjacent modules that
turn out not to be substantively affected get re-verified unnecessarily. This
mirrors the survey's own framing: propagation should catch every affected
module "without re-running Discovery on the whole repo" (Sec. VII), not
achieve perfect precision at the risk of missing one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Set

from opspilot.memory.repo_dependency_graph import RepoDependencyGraph


@dataclass
class PropagationResult:
    changed_node: str
    scheduled_for_reverification: List[str]
    total_repo_nodes: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def scope_fraction(self) -> float:
        """Fraction of the repo re-verification touches -- the efficiency
        metric a "just re-verify everything" baseline would always report as
        1.0 regardless of the actual blast radius of the change."""
        if self.total_repo_nodes == 0:
            return 0.0
        return len(self.scheduled_for_reverification) / self.total_repo_nodes


class ChangePropagationAgent:
    def __init__(self, repo_graph: RepoDependencyGraph):
        self.repo_graph = repo_graph

    def propagate(self, changed_node: str) -> PropagationResult:
        dependents = self.repo_graph.structural_dependents(changed_node)
        # exclude non-module nodes (COPYBOOK/TABLE) from the re-verification
        # worklist -- only modules (PROGRAM/PROCEDURE nodes) are ever
        # re-verified; shared copybooks/tables are graph structure, not
        # verification targets themselves
        module_dependents = [
            n for n in dependents
            if self.repo_graph.graph.nodes.get(n, {}).get("node_type") in ("PROGRAM", "PROCEDURE", None)
        ]
        return PropagationResult(
            changed_node=changed_node,
            scheduled_for_reverification=sorted(module_dependents),
            total_repo_nodes=self.repo_graph.node_count,
        )

    def propagate_many(self, changed_nodes: List[str]) -> PropagationResult:
        """Propagates a batch of simultaneous changes (e.g. several fields in
        the same copybook edited together) as one combined worklist."""
        all_dependents: Set[str] = set()
        for node in changed_nodes:
            all_dependents |= self.repo_graph.structural_dependents(node)
        module_dependents = [
            n for n in all_dependents
            if self.repo_graph.graph.nodes.get(n, {}).get("node_type") in ("PROGRAM", "PROCEDURE", None)
        ]
        return PropagationResult(
            changed_node=",".join(changed_nodes),
            scheduled_for_reverification=sorted(module_dependents),
            total_repo_nodes=self.repo_graph.node_count,
        )
