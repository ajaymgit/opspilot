"""Extracts Discovery-time features used to predict a per-module iteration budget.

These features are exactly the class of information already available after
Phase 1 (deterministic static analysis) and before Phase 3 begins -- the
Pre-Refinement Predictor must not depend on anything the Coder/Verifier loop
produces, since its entire point is to size the budget *before* the first
attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ModuleFeatures:
    embedded_sql: bool
    cics_handler: bool
    cyclomatic_complexity: float  # normalized proxy, roughly 1..30
    dependency_count: int

    def to_vector(self):
        return [
            1.0 if self.embedded_sql else 0.0,
            1.0 if self.cics_handler else 0.0,
            float(self.cyclomatic_complexity),
            float(self.dependency_count),
        ]

    @staticmethod
    def feature_names():
        return ["embedded_sql", "cics_handler", "cyclomatic_complexity", "dependency_count"]


_CICS_MARKERS = ("EXEC CICS", "CICS")


def extract_module_features(analysis_output: Dict[str, Any], dependency_graph: Dict[str, Any] = None) -> ModuleFeatures:
    """Derives `ModuleFeatures` from a Phase-1 `analysis_output` (and optionally
    the Phase-1 dependency graph) as produced by
    `opspilot.analysis.parsers.cobol_parser` / `plsql_parser` and
    `opspilot.analysis.dependency_graph.DependencyGraphBuilder`."""
    embedded_sql_list = analysis_output.get("embedded_sql", []) or []
    embedded_sql = len(embedded_sql_list) > 0

    raw_text_markers = " ".join(
        str(s.get("name", "")) for s in analysis_output.get("sections_or_procedures", []) or []
    ).upper()
    cics_handler = any(marker in raw_text_markers for marker in _CICS_MARKERS) or any(
        "CICS" in str(sql.get("statement_type", "")).upper() for sql in embedded_sql_list
    )

    sections = analysis_output.get("sections_or_procedures", []) or []
    call_graph = analysis_output.get("call_graph", {}) or {}
    n_edges = len(call_graph.get("edges", []) or [])
    n_sections = max(1, len(sections))
    # Cyclomatic-complexity proxy: 1 base decision point per section plus one
    # per call-graph edge (branch/PERFORM target), normalized per section --
    # deliberately simple and explainable rather than a full McCabe computation,
    # since the predictor only needs a monotonic proxy, not a certified metric.
    cyclomatic_complexity = 1.0 + (n_edges / n_sections)

    if dependency_graph:
        dependency_count = int(dependency_graph.get("edge_count", len(dependency_graph.get("edges", []) or [])))
    else:
        dependency_count = len(analysis_output.get("copybooks_or_includes", []) or []) + len(
            analysis_output.get("external_calls", []) or []
        )

    return ModuleFeatures(
        embedded_sql=embedded_sql,
        cics_handler=cics_handler,
        cyclomatic_complexity=cyclomatic_complexity,
        dependency_count=dependency_count,
    )
