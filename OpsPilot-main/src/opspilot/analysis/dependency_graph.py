"""Directed dependency graph construction and serialization using NetworkX."""

from typing import Dict, Any, List

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    nx = None
    HAS_NETWORKX = False


class _FallbackDiGraph:
    """Lightweight pure-Python directed graph fallback when networkx is absent."""

    def __init__(self):
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: Dict[tuple, Dict[str, Any]] = {}
        self._succ: Dict[str, set] = {}
        self._pred: Dict[str, set] = {}

    def add_node(self, node: str, **attrs):
        if node not in self._nodes:
            self._nodes[node] = {}
            self._succ[node] = set()
            self._pred[node] = set()
        self._nodes[node].update(attrs)

    def add_edge(self, u: str, v: str, **attrs):
        self.add_node(u)
        self.add_node(v)
        self._edges[(u, v)] = attrs
        self._succ[u].add(v)
        self._pred[v].add(u)

    def nodes(self, data: bool = False):
        if data:
            return list(self._nodes.items())
        return list(self._nodes.keys())

    def edges(self, data: bool = False):
        if data:
            return [(u, v, self._edges[(u, v)]) for (u, v) in self._edges]
        return list(self._edges.keys())

    def topological_sort(self) -> List[str]:
        in_deg = {n: len(self._pred[n]) for n in self._nodes}
        queue = [n for n, d in in_deg.items() if d == 0]
        order = []
        while queue:
            curr = queue.pop(0)
            order.append(curr)
            for s in self._succ.get(curr, []):
                in_deg[s] -= 1
                if in_deg[s] == 0:
                    queue.append(s)
        return order if len(order) == len(self._nodes) else list(self._nodes.keys())


class DependencyGraphBuilder:
    """Builds and serializes a directed graph from pre-parsed AST summaries."""

    def __init__(self, analysis_data: Dict[str, Any]):
        self.analysis_data = analysis_data
        self.graph = nx.DiGraph() if HAS_NETWORKX else _FallbackDiGraph()
        self._build_graph()

    def _build_graph(self):
        program_name = self.analysis_data.get("program_name", "PROGRAM")
        self.graph.add_node(program_name, node_type="PROGRAM")

        # Add section / paragraph nodes and call edges
        call_graph = self.analysis_data.get("call_graph", {})
        for node in call_graph.get("nodes", []):
            self.graph.add_node(node, node_type="PROCEDURE")

        for edge in call_graph.get("edges", []):
            self.graph.add_edge(edge["caller"], edge["callee"], relationship=edge.get("type", "CALL"))

        # Add copybook / include nodes
        for copybook in self.analysis_data.get("copybooks_or_includes", []):
            self.graph.add_node(copybook, node_type="COPYBOOK")
            self.graph.add_edge(program_name, copybook, relationship="INCLUDES")

        # Add SQL Table nodes
        for sql in self.analysis_data.get("embedded_sql", []):
            for table in sql.get("tables", []):
                self.graph.add_node(table, node_type="TABLE")
                self.graph.add_edge(program_name, table, relationship=sql.get("statement_type", "SQL"))

    def to_dict(self) -> Dict[str, Any]:
        """Serializes directed graph structure to JSON-friendly dictionary."""
        nodes = []
        for node, attrs in self.graph.nodes(data=True):
            nodes.append({"id": node, **attrs})

        edges = []
        for u, v, attrs in self.graph.edges(data=True):
            edges.append({"source": u, "target": v, **attrs})

        return {
            "program": self.analysis_data.get("program_name"),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges
        }

    def get_execution_order(self) -> List[str]:
        """Calculates topological sort order if graph is DAG, else returns node list."""
        if HAS_NETWORKX:
            try:
                return list(nx.topological_sort(self.graph))
            except nx.NetworkXUnfeasible:
                return list(self.graph.nodes)
        else:
            return self.graph.topological_sort()
