"""Evaluation harness for RepoMind's Semantic Memory: a standard information-
retrieval evaluation (precision@k against topic-labeled ground truth), not a
propagation-graph evaluation. This is deliberately structured differently from
`evaluate_propagation.py` because it is testing a genuinely different
mechanism -- text retrieval quality, not graph traversal correctness.

A synthetic corpus of `DecisionEntry` records is generated across several
distinct "topics" (COBOL idioms a Coder agent might have logged rationale
about: date-conversion routines, packed-decimal rounding, CICS error handling,
etc.), each with topic-specific vocabulary plus some shared boilerplate
phrasing (so topics aren't trivially separable by a single keyword). A query
drawn from the same topic distribution is then scored by whether the
retrieved top-k entries share the query's topic -- precision@k -- against a
random-retrieval baseline.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Dict, List

from opspilot.memory.semantic_memory import DecisionEntry, SemanticMemory

TOPIC_VOCAB: Dict[str, List[str]] = {
    "date_conversion": [
        "converted the packed date field using a YYYYMMDD to LocalDate mapping",
        "the copybook stores dates in Julian format so we normalize via a custom DateConverter utility",
        "century window logic added to disambiguate two-digit legacy year fields",
        "date arithmetic must account for the COBOL epoch offset before converting to java.time",
    ],
    "packed_decimal_rounding": [
        "packed decimal COMP-3 field rounded using half-up per the original COBOL ROUNDED clause",
        "BigDecimal scale preserved to match the legacy PIC 9(7)V99 implied decimal precision",
        "currency rounding mode set to HALF_UP to replicate mainframe COMPUTE ROUNDED behavior",
        "truncation vs rounding discrepancy found in the original COBOL and preserved intentionally",
    ],
    "cics_error_handling": [
        "CICS EXEC HANDLE CONDITION mapped to a checked exception per response code",
        "NOTFND response code from the CICS READ translated into an Optional empty return",
        "DFHRESP codes enumerated into a typed exception hierarchy for the transaction handler",
        "abend recovery path preserved by wrapping the CICS call in a retry-with-backoff",
    ],
    "null_and_default_handling": [
        "COBOL LOW-VALUES field mapped to Java null rather than empty string to preserve semantics",
        "SPACES-filled alphanumeric field defaulted to an empty string on migration",
        "uninitialized WORKING-STORAGE numeric field defaulted to zero per COBOL implicit initialization",
        "missing optional record field treated as Optional.empty rather than a sentinel value",
    ],
    "batch_sequencing": [
        "PERFORM UNTIL loop over the sequential file converted to a Java iterator-based batch reader",
        "control-break logic on the sorted key field reimplemented with a grouping collector",
        "end-of-file sentinel record handling preserved to avoid off-by-one in the batch total",
        "checkpoint/restart logic for the overnight batch job ported to a resumable job step",
    ],
}


def generate_decision_corpus(n_per_topic: int = 30, seed: int = 42) -> List[DecisionEntry]:
    rng = random.Random(seed)
    entries = []
    boilerplate = ["reviewed during Phase 3 self-refine", "verified against the legacy test fixture",
                   "flagged for governance review", "logged for future reference"]
    idx = 0
    for topic, phrases in TOPIC_VOCAB.items():
        for _ in range(n_per_topic):
            rationale = rng.choice(phrases) + ". " + rng.choice(boilerplate) + "."
            entries.append(DecisionEntry(
                entry_id=f"e{idx}", module_id=f"MOD{idx:04d}", rationale=rationale,
                edge_cases=[rng.choice(phrases)], tags=[topic],
            ))
            idx += 1
    rng.shuffle(entries)
    return entries


def run_evaluation(n_per_topic: int = 30, n_queries: int = 100, top_k: int = 5, seed: int = 42,
                    output_dir: Path = Path("workspace/repomind_eval")) -> Dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    corpus = generate_decision_corpus(n_per_topic=n_per_topic, seed=seed)
    memory = SemanticMemory()
    for entry in corpus:
        memory.write(entry)

    rng = random.Random(seed + 1)
    topics = list(TOPIC_VOCAB.keys())

    semantic_precisions = []
    random_precisions = []
    for _ in range(n_queries):
        topic = rng.choice(topics)
        query_text = rng.choice(TOPIC_VOCAB[topic])

        results = memory.search(query_text, top_k=top_k)
        retrieved_topics = [r["entry"].tags[0] for r in results]
        semantic_hits = sum(1 for t in retrieved_topics if t == topic)
        semantic_precisions.append(semantic_hits / top_k)

        random_sample = rng.sample(corpus, min(top_k, len(corpus)))
        random_hits = sum(1 for e in random_sample if e.tags[0] == topic)
        random_precisions.append(random_hits / top_k)

    summary = {
        "n_corpus_entries": len(corpus),
        "n_topics": len(topics),
        "top_k": top_k,
        "n_queries": n_queries,
        "semantic_memory_avg_precision_at_k": round(sum(semantic_precisions) / n_queries, 4),
        "random_baseline_avg_precision_at_k": round(sum(random_precisions) / n_queries, 4),
        "topic_base_rate": round(1.0 / len(topics), 4),
    }

    with open(output_dir / "semantic_recall_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


def main():
    parser = argparse.ArgumentParser(description="Run RepoMind semantic memory recall evaluation")
    parser.add_argument("--n-per-topic", type=int, default=30)
    parser.add_argument("--n-queries", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=str, default="workspace/repomind_eval")
    args = parser.parse_args()

    summary = run_evaluation(n_per_topic=args.n_per_topic, n_queries=args.n_queries, top_k=args.top_k,
                              seed=args.seed, output_dir=Path(args.output_dir))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
