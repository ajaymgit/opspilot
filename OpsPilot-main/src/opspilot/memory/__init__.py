"""RepoMind: persistent, repo-scale project memory and targeted change
propagation, spanning all four OpsPilot phases rather than sitting inside one.

Implements the research direction the survey names explicitly in Section V-A
and Section VII: "consistent repository-scale project state remains an open
research problem rather than a demonstrated capability" and "persistent,
shared long-term agent memory recording translated modules, discovered edge
cases, and converged refinement strategies would reduce redundant re-analysis
across long-running migrations" (citing AutoGen [3]).

Design summary
---------------
    Repo Dependency Graph (`repo_dependency_graph.py`)
        A persistent, JSON-backed, repo-wide dependency graph (module -> module
        CALL/PERFORM edges, module -> copybook COPY/INCLUDE edges), built
        incrementally across a migration run instead of being recomputed
        per-module. Extends `opspilot.analysis.dependency_graph`'s per-file
        graph builder to a whole-repo, persistent structure.

    Semantic Memory (`semantic_memory.py`)
        A lexical (TF-IDF) memory store of past decision rationale and
        discovered edge cases, so a later module facing a similar pattern
        (e.g. "how was this DATE-CONVERT copybook idiom handled elsewhere?")
        can retrieve prior reasoning instead of re-deriving it. Documented as
        a lexical stand-in for a real embedding-backed vector store (Weaviate,
        Pinecone, ...), which this offline environment cannot call out to.

    Change Propagation Agent (`change_propagation_agent.py`)
        When a module or shared copybook changes, walks the dependency graph
        to find every module that structurally depends on it (directly or
        transitively) and schedules those for *targeted re-verification*
        (Verifier only, not a full Coder re-translation) -- global refactoring
        propagation without re-running Discovery on the whole repo.

This subpackage is intentionally decoupled from the base pipeline: importing
it has no effect on `MasterOrchestrator` unless explicitly wired in.
"""

from opspilot.memory.repo_dependency_graph import RepoDependencyGraph
from opspilot.memory.semantic_memory import DecisionEntry, SemanticMemory
from opspilot.memory.change_propagation_agent import ChangePropagationAgent, PropagationResult
from opspilot.memory.memory_writer import MemoryWriter

__all__ = [
    "RepoDependencyGraph",
    "DecisionEntry",
    "SemanticMemory",
    "ChangePropagationAgent",
    "PropagationResult",
    "MemoryWriter",
]
