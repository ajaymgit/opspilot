"""Semantic Memory: recall of past Phase-1/Phase-3 decision rationale and
discovered edge cases, so a module facing a familiar pattern can retrieve prior
reasoning instead of re-deriving it from scratch (Sec. VII: "persistent, shared
long-term agent memory recording translated modules, discovered edge cases,
and converged refinement strategies").

This environment has no network access to a real embedding API or a hosted
vector database (Weaviate, Pinecone, ...), so this implementation is a lexical
(TF-IDF + cosine similarity) memory store, not a semantic-embedding one. It is
built and evaluated honestly as that: the class and file names say "semantic"
because that is the survey's own term for the capability, but the retrieval
quality numbers reported by `evaluate_recall.py` are for TF-IDF, and would
likely improve with a real embedding backend, which is exactly the trade-off
documented in the implementation notes -- not glossed over here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class DecisionEntry:
    entry_id: str
    module_id: str
    rationale: str
    edge_cases: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def searchable_text(self) -> str:
        return " ".join([self.rationale, " ".join(self.edge_cases), " ".join(self.tags)])


class SemanticMemory:
    """TF-IDF-backed nearest-neighbor recall over logged `DecisionEntry`
    records. The index is rebuilt lazily on `search()` after any write, since
    this is a documentation/evaluation-scale store (hundreds to low thousands
    of entries), not a production ANN index."""

    def __init__(self):
        self.entries: List[DecisionEntry] = []
        self._vectorizer: Optional[TfidfVectorizer] = None
        self._matrix = None
        self._dirty = True

    def write(self, entry: DecisionEntry) -> None:
        self.entries.append(entry)
        self._dirty = True

    def _rebuild_index(self) -> None:
        if not self.entries:
            self._vectorizer, self._matrix = None, None
            self._dirty = False
            return
        texts = [e.searchable_text() for e in self.entries]
        self._vectorizer = TfidfVectorizer(stop_words="english", min_df=1)
        self._matrix = self._vectorizer.fit_transform(texts)
        self._dirty = False

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if self._dirty:
            self._rebuild_index()
        if not self.entries or self._vectorizer is None:
            return []
        query_vec = self._vectorizer.transform([query])
        similarities = cosine_similarity(query_vec, self._matrix)[0]
        ranked_idx = similarities.argsort()[::-1][:top_k]
        return [
            {"entry": self.entries[i], "similarity": float(similarities[i])}
            for i in ranked_idx if similarities[i] > 0.0
        ]

    # -- persistence -----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {"entries": [asdict(e) for e in self.entries]}

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Optional["SemanticMemory"]:
        path = Path(path)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        memory = cls()
        for e in data.get("entries", []):
            memory.entries.append(DecisionEntry(**e))
        memory._dirty = True
        return memory
