"""networkx build/load/traverse for the policy knowledge graph.

MultiDiGraph, loaded once into a module-level singleton at process start (see
get_graph_store); rebuildable from policy_graph_edges when running against Postgres.
"""

import pickle
from pathlib import Path
from typing import Any

import networkx as nx

from app.core.settings import Settings

_singleton: "PolicyGraphStore | None" = None


class PolicyGraphStore:
    def __init__(self) -> None:
        self._graph: nx.MultiDiGraph = nx.MultiDiGraph()

    def add_edges(self, edges: list[dict[str, Any]]) -> None:
        for edge in edges:
            self._graph.add_node(edge["src"], type=edge["src_type"])
            self._graph.add_node(edge["dst"], type=edge["dst_type"])
            self._graph.add_edge(
                edge["src"],
                edge["dst"],
                relation=edge["relation"],
                clause_id=edge.get("clause_id"),
                **edge.get("properties", {}),
            )

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as f:
            pickle.dump(self._graph, f)

    def load(self, path: str | Path) -> None:
        with Path(path).open("rb") as f:
            self._graph = pickle.load(f)

    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    def ego_subgraph_triples(self, seeds: list[str], hops: int) -> list[str]:
        """nx.ego_graph per seed -> union -> serialised as readable triples with clause ids."""
        triples: list[str] = []
        seen: set[tuple[str, str, str]] = set()
        for seed in seeds:
            if seed not in self._graph:
                continue
            subgraph = nx.ego_graph(self._graph, seed, radius=hops)
            for src, dst, data in subgraph.edges(data=True):
                relation = data.get("relation", "related_to")
                key = (src, relation, dst)
                if key in seen:
                    continue
                seen.add(key)
                clause_id = data.get("clause_id")
                properties = {
                    k: v for k, v in data.items() if k not in ("relation", "clause_id")
                }
                props_suffix = f" {properties}" if properties else ""
                clause_suffix = f"  [clause: {clause_id}]" if clause_id else ""
                triples.append(f"{src} —{relation}→ {dst}{props_suffix}{clause_suffix}")
        return triples


def get_graph_store(settings: Settings) -> PolicyGraphStore:
    """Loaded once into a process-level singleton, per DEVELOPMENT_PLAN.md's GraphRAG
    chapter. Callers that rebuild the graph (pipelines/data_pipeline.py) use their own
    PolicyGraphStore() instance instead — this singleton is for read-only runtime use."""
    global _singleton
    if _singleton is None:
        _singleton = PolicyGraphStore()
        graph_path = Path(settings.documents_dir).parent / "graph" / "claims.gpickle"
        if graph_path.exists():
            _singleton.load(graph_path)
    return _singleton
