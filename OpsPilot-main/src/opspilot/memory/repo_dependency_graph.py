"""Persistent, repo-scale dependency graph.

`opspilot.analysis.dependency_graph.DependencyGraphBuilder` builds one graph
per module, scoped to a single Discovery pass, and is discarded once that
module's pipeline run ends. `RepoDependencyGraph` is the repo-scale
counterpart: it accumulates every module's graph into one persistent,
JSON-backed structure that survives across modules (and across process
restarts, via `save`/`load`), which is the prerequisite for the "consistent
repository-scale project state" the survey flags as unsolved (Sec. V-A).

Nodes are typed (PROGRAM, PROCEDURE, COPYBOOK, TABLE) exactly as in the
per-module builder; edges accumulate from every module processed so far, so a
COPYBOOK or TABLE node's in-edges naturally represent every module that
depends on it -- which is exactly the information `ChangePropagationAgent`
needs to answer "what does changing this copybook affect?"
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import networkx as nx


class RepoDependencyGraph:
    def __init__(self):
        self.graph = nx.DiGraph()

    # -- ingestion -----------------------------------------------------

    def ingest_module_graph(self, module_graph_dict: Dict[str, Any]) -> None:
        """Merges one module's `DependencyGraphBuilder.to_dict()` output into
        the persistent repo graph. Idempotent: re-ingesting the same module
        (e.g. after a re-verification pass) simply overwrites its edges rather
        than duplicating them, since NetworkX node/edge keys are already
        de-duplicating by (source, target) identity."""
        for node in module_graph_dict.get("nodes", []):
            node_id = node["id"]
            attrs = {k: v for k, v in node.items() if k != "id"}
            if self.graph.has_node(node_id):
                self.graph.nodes[node_id].update(attrs)
            else:
                self.graph.add_node(node_id, **attrs)

        for edge in module_graph_dict.get("edges", []):
            self.graph.add_edge(edge["source"], edge["target"],
                                 **{k: v for k, v in edge.items() if k not in ("source", "target")})

    def add_module(self, module_name: str, depends_on: Optional[List[str]] = None,
                   node_type: str = "PROGRAM") -> None:
        """Lower-level entry point for synthetic/test data that doesn't go
        through a full `DependencyGraphBuilder` pass."""
        if not self.graph.has_node(module_name):
            self.graph.add_node(module_name, node_type=node_type)
        for dep in (depends_on or []):
            if not self.graph.has_node(dep):
                self.graph.add_node(dep, node_type="COPYBOOK")
            self.graph.add_edge(module_name, dep, relationship="DEPENDS_ON")

    # -- queries ---------------------------------------------------------

    def structural_dependents(self, node_id: str) -> Set[str]:
        """Every node that structurally depends on `node_id`, directly or
        transitively -- i.e. everyone who would need to be at least considered
        if `node_id` changes. This is deliberately the *conservative*
        (superset) answer: it is the set `ChangePropagationAgent` proposes for
        targeted re-verification, and by construction it can never miss a
        truly-impacted module, only over-include structurally-adjacent ones
        that turn out not to be substantively affected."""
        if node_id not in self.graph:
            return set()
        return set(nx.ancestors(self.graph, node_id))

    def direct_dependents(self, node_id: str) -> Set[str]:
        if node_id not in self.graph:
            return set()
        return set(self.graph.predecessors(node_id))

    def dependencies_of(self, module_name: str) -> Set[str]:
        if module_name not in self.graph:
            return set()
        return set(nx.descendants(self.graph, module_name))

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    # -- persistence -------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "nodes": [{"id": n, **attrs} for n, attrs in self.graph.nodes(data=True)],
            "edges": [{"source": u, "target": v, **attrs} for u, v, attrs in self.graph.edges(data=True)],
        }

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Optional["RepoDependencyGraph"]:
        path = Path(path)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        repo_graph = cls()
        repo_graph.ingest_module_graph(data)
        return repo_graph
