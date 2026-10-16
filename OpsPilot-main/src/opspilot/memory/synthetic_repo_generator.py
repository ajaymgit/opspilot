"""Generates a synthetic multi-module "mini-repo" with a known, ground-truth
dependency structure, used only for offline evaluation of change propagation.

Structure: `n_modules` modules, `n_copybooks` shared copybooks (some "hub"
copybooks used by many modules, some rare), and a DAG of module-to-module CALL
edges layered on top (so impact can also propagate transitively through call
chains, not only through shared copybooks). Each module that uses a copybook
references only a *subset* of that copybook's fields -- this is what makes the
propagation evaluation non-tautological: "structurally depends on the
copybook" (what the dependency graph can see) is a conservative superset of
"actually references the specific field that changed" (the ground truth for
whether a module truly needs re-verification).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

import networkx as nx

from opspilot.memory.repo_dependency_graph import RepoDependencyGraph


@dataclass
class SyntheticRepo:
    repo_graph: RepoDependencyGraph
    call_graph: nx.DiGraph  # module-only subgraph, for transitive "truly impacted" propagation
    module_copybook_fields: Dict[Tuple[str, str], Set[str]]  # (module, copybook) -> fields referenced
    copybook_fields: Dict[str, List[str]]
    modules: List[str] = field(default_factory=list)
    copybooks: List[str] = field(default_factory=list)


def generate_synthetic_repo(
    n_modules: int = 60,
    n_copybooks: int = 10,
    fields_per_copybook: int = 6,
    hub_copybook_fraction: float = 0.3,
    max_call_edges_per_module: int = 2,
    seed: int = 42,
) -> SyntheticRepo:
    rng = random.Random(seed)
    modules = [f"MOD{i:03d}" for i in range(n_modules)]
    copybooks = [f"CPY{i:02d}" for i in range(n_copybooks)]
    n_hubs = max(1, round(n_copybooks * hub_copybook_fraction))
    hub_copybooks = set(copybooks[:n_hubs])

    copybook_fields = {cpy: [f"FIELD-{cpy}-{j}" for j in range(fields_per_copybook)] for cpy in copybooks}

    repo_graph = RepoDependencyGraph()
    call_graph = nx.DiGraph()
    call_graph.add_nodes_from(modules)
    module_copybook_fields: Dict[Tuple[str, str], Set[str]] = {}

    for module in modules:
        repo_graph.graph.add_node(module, node_type="PROGRAM")

        # copybook usage: hub copybooks used by many modules, others rarely
        n_deps = rng.randint(1, 3)
        chosen = set()
        for _ in range(n_deps):
            if rng.random() < 0.6 and hub_copybooks:
                chosen.add(rng.choice(list(hub_copybooks)))
            else:
                chosen.add(rng.choice(copybooks))
        for cpy in chosen:
            repo_graph.graph.add_node(cpy, node_type="COPYBOOK")
            repo_graph.graph.add_edge(module, cpy, relationship="INCLUDES")
            n_fields_used = rng.randint(1, max(1, fields_per_copybook // 2))
            module_copybook_fields[(module, cpy)] = set(rng.sample(copybook_fields[cpy], n_fields_used))

    # layer a DAG of CALL edges on top (caller index < callee index avoided;
    # here we call "backwards" in index order so callers depend on
    # already-defined callees, keeping the graph acyclic)
    for i, module in enumerate(modules):
        if i == 0:
            continue
        n_calls = rng.randint(0, max_call_edges_per_module)
        possible_callees = modules[:i]
        if not possible_callees:
            continue
        for _ in range(n_calls):
            callee = rng.choice(possible_callees)
            repo_graph.graph.add_edge(module, callee, relationship="CALLS")
            call_graph.add_edge(module, callee)

    return SyntheticRepo(
        repo_graph=repo_graph, call_graph=call_graph, module_copybook_fields=module_copybook_fields,
        copybook_fields=copybook_fields, modules=modules, copybooks=copybooks,
    )


def truly_impacted_modules(repo: SyntheticRepo, changed_copybook: str, changed_field: str) -> Set[str]:
    """Ground truth: modules that directly reference the specific changed
    field, plus every module that transitively calls one of those (impact
    propagates through call chains, not only through direct copybook usage)."""
    directly_impacted = {
        module for (module, cpy), fields in repo.module_copybook_fields.items()
        if cpy == changed_copybook and changed_field in fields
    }
    impacted = set(directly_impacted)
    for module in directly_impacted:
        if module in repo.call_graph:
            impacted |= nx.ancestors(repo.call_graph, module)
    return impacted
