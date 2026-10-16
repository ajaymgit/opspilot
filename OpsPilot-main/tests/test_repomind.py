"""Unit tests for RepoMind: persistent repo-scale memory and change propagation
(Idea 4)."""

from pathlib import Path

from opspilot.memory.change_propagation_agent import ChangePropagationAgent
from opspilot.memory.evaluate_propagation import run_evaluation as run_propagation_evaluation
from opspilot.memory.evaluate_semantic_recall import generate_decision_corpus, run_evaluation as run_recall_evaluation
from opspilot.memory.memory_writer import MemoryWriter
from opspilot.memory.repo_dependency_graph import RepoDependencyGraph
from opspilot.memory.semantic_memory import DecisionEntry, SemanticMemory
from opspilot.memory.synthetic_repo_generator import generate_synthetic_repo, truly_impacted_modules


# ---------------------------------------------------------------------------
# RepoDependencyGraph
# ---------------------------------------------------------------------------

def test_structural_dependents_direct_and_transitive():
    graph = RepoDependencyGraph()
    graph.add_module("MOD_A", depends_on=["CPY_SHARED"])
    graph.graph.add_edge("MOD_B", "MOD_A", relationship="CALLS")  # B calls A
    graph.graph.add_node("MOD_B", node_type="PROGRAM")

    dependents = graph.structural_dependents("CPY_SHARED")
    assert "MOD_A" in dependents  # direct
    assert "MOD_B" in dependents  # transitive, via MOD_B -> MOD_A -> CPY_SHARED


def test_structural_dependents_unrelated_module_excluded():
    graph = RepoDependencyGraph()
    graph.add_module("MOD_A", depends_on=["CPY_1"])
    graph.add_module("MOD_C", depends_on=["CPY_2"])
    dependents = graph.structural_dependents("CPY_1")
    assert "MOD_C" not in dependents


def test_repo_dependency_graph_save_and_load_roundtrip(tmp_path):
    graph = RepoDependencyGraph()
    graph.add_module("MOD_A", depends_on=["CPY_1"])
    path = Path(tmp_path) / "graph.json"
    graph.save(path)

    loaded = RepoDependencyGraph.load(path)
    assert loaded is not None
    assert loaded.node_count == graph.node_count
    assert "MOD_A" in loaded.structural_dependents("CPY_1")


def test_ingest_module_graph_is_idempotent():
    graph = RepoDependencyGraph()
    module_graph_dict = {
        "nodes": [{"id": "PROG1", "node_type": "PROGRAM"}, {"id": "CPY1", "node_type": "COPYBOOK"}],
        "edges": [{"source": "PROG1", "target": "CPY1", "relationship": "INCLUDES"}],
    }
    graph.ingest_module_graph(module_graph_dict)
    graph.ingest_module_graph(module_graph_dict)  # re-ingest same module
    assert graph.edge_count == 1
    assert graph.node_count == 2


# ---------------------------------------------------------------------------
# ChangePropagationAgent
# ---------------------------------------------------------------------------

def test_propagation_agent_flags_only_modules_not_copybook_nodes():
    graph = RepoDependencyGraph()
    graph.add_module("MOD_A", depends_on=["CPY_SHARED"])
    graph.add_module("MOD_B", depends_on=["CPY_SHARED"])
    agent = ChangePropagationAgent(graph)
    result = agent.propagate("CPY_SHARED")
    assert set(result.scheduled_for_reverification) == {"MOD_A", "MOD_B"}
    assert "CPY_SHARED" not in result.scheduled_for_reverification


def test_propagation_scope_fraction_less_than_one_for_partial_repo():
    graph = RepoDependencyGraph()
    for i in range(10):
        graph.add_module(f"MOD_{i}", depends_on=["CPY_RARE"] if i == 0 else ["CPY_OTHER"])
    agent = ChangePropagationAgent(graph)
    result = agent.propagate("CPY_RARE")
    assert result.scope_fraction < 1.0
    assert result.scheduled_for_reverification == ["MOD_0"]


def test_propagation_never_misses_a_structurally_reachable_module():
    """Regression guard: structural_dependents (and therefore propagation) must
    be a strict superset of the ground-truth truly-impacted set on a real
    synthetic repo -- this is RepoMind's core safety property."""
    repo = generate_synthetic_repo(n_modules=40, n_copybooks=8, seed=3)
    agent = ChangePropagationAgent(repo.repo_graph)
    for cpy in repo.copybooks:
        for field in repo.copybook_fields[cpy][:2]:
            truth = truly_impacted_modules(repo, cpy, field)
            predicted = set(agent.propagate(cpy).scheduled_for_reverification)
            assert truth.issubset(predicted), f"missed modules for {cpy}/{field}: {truth - predicted}"


# ---------------------------------------------------------------------------
# SemanticMemory
# ---------------------------------------------------------------------------

def test_semantic_memory_retrieves_topically_similar_entry():
    memory = SemanticMemory()
    memory.write(DecisionEntry(entry_id="1", module_id="M1",
                                rationale="packed decimal COMP-3 rounded half-up per ROUNDED clause",
                                tags=["packed_decimal_rounding"]))
    memory.write(DecisionEntry(entry_id="2", module_id="M2",
                                rationale="CICS EXEC HANDLE CONDITION mapped to a checked exception",
                                tags=["cics_error_handling"]))
    results = memory.search("how should COMP-3 rounding be handled", top_k=1)
    assert len(results) == 1
    assert results[0]["entry"].entry_id == "1"


def test_semantic_memory_empty_store_returns_no_results():
    memory = SemanticMemory()
    assert memory.search("anything") == []


def test_semantic_memory_save_and_load_roundtrip(tmp_path):
    memory = SemanticMemory()
    memory.write(DecisionEntry(entry_id="1", module_id="M1", rationale="date conversion via LocalDate mapping"))
    path = Path(tmp_path) / "memory.json"
    memory.save(path)
    loaded = SemanticMemory.load(path)
    assert loaded is not None
    assert len(loaded.entries) == 1
    results = loaded.search("date conversion")
    assert len(results) == 1


# ---------------------------------------------------------------------------
# MemoryWriter (integration glue)
# ---------------------------------------------------------------------------

def test_memory_writer_records_graph_and_semantic_entry_together():
    graph = RepoDependencyGraph()
    memory = SemanticMemory()
    writer = MemoryWriter(graph, memory)

    module_graph_dict = {
        "nodes": [{"id": "PROG1", "node_type": "PROGRAM"}, {"id": "CPY1", "node_type": "COPYBOOK"}],
        "edges": [{"source": "PROG1", "target": "CPY1", "relationship": "INCLUDES"}],
    }
    writer.record_verified_module(
        module_id="PROG1", module_graph_dict=module_graph_dict,
        rationale="mapped LOW-VALUES to null", edge_cases=["null handling"], tags=["null_and_default_handling"],
    )
    assert graph.node_count == 2
    assert len(memory.entries) == 1
    assert memory.entries[0].module_id == "PROG1"


# ---------------------------------------------------------------------------
# Evaluation harnesses (small-scale, fast)
# ---------------------------------------------------------------------------

def test_propagation_evaluation_harness_runs_and_repo_mind_never_loses_recall(tmp_path):
    summary, scenarios = run_propagation_evaluation(n_modules=30, n_copybooks=6, n_scenarios=40,
                                                       output_dir=Path(tmp_path))
    assert summary["repo_mind"]["avg_recall"] == 1.0
    assert summary["repo_mind"]["avg_n_flagged"] <= summary["verify_everything"]["avg_n_flagged"]


def test_semantic_recall_evaluation_harness_beats_random_baseline(tmp_path):
    summary = run_recall_evaluation(n_per_topic=15, n_queries=60, top_k=5, output_dir=Path(tmp_path))
    assert summary["semantic_memory_avg_precision_at_k"] > summary["random_baseline_avg_precision_at_k"]


def test_generate_decision_corpus_reproducible_with_seed():
    a = generate_decision_corpus(n_per_topic=5, seed=1)
    b = generate_decision_corpus(n_per_topic=5, seed=1)
    assert [e.rationale for e in a] == [e.rationale for e in b]
