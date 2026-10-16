"""LinUCB contextual bandit over (risk-category, threshold) arms.

Reference: Li, Chu, Langford, Schapire, "A Contextual-Bandit Approach to
Personalized News Article Recommendation", WWW 2010.

The bandit does not choose "approve/reject" directly -- it chooses *which
threshold* to apply for the current context. The acceptance decision is then a
deterministic comparison of the observed risk score against the chosen threshold,
which keeps the actual guardrail decision auditable (Section IV/Table I's
traceability requirement) even though the threshold itself is learned.

Arms are a small, fixed, discretized ladder of threshold candidates (e.g.
0.1 .. 0.9). This keeps the action space small enough to learn quickly from a
realistic HITL decision volume, per the survey's own framing of guardrail
adaptation as expensive-to-label ("needs a labeled corpus of past escalation
decisions").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np


class LinUCBBandit:
    """Disjoint LinUCB bandit: one (A, b) pair per arm, shared context features."""

    def __init__(self, arms: List[float], context_dim: int, alpha: float = 1.0, seed: Optional[int] = None):
        if not arms:
            raise ValueError("LinUCBBandit requires at least one arm (threshold candidate).")
        self.arms = list(arms)
        self.context_dim = context_dim
        self.alpha = alpha
        self.A: Dict[float, np.ndarray] = {a: np.eye(context_dim) for a in self.arms}
        self.b: Dict[float, np.ndarray] = {a: np.zeros(context_dim) for a in self.arms}
        self.pull_counts: Dict[float, int] = {a: 0 for a in self.arms}
        self._rng = np.random.RandomState(seed)

    def select_arm(self, context: np.ndarray) -> float:
        """Selects the threshold arm with highest upper-confidence estimate.

        Ties (all arms start at an identical A=I, b=0 baseline, so early calls on
        novel contexts genuinely tie) are broken uniformly at random rather than
        always favoring the first arm in the list -- without this, disjoint LinUCB
        with a fixed iteration order pathologically locks onto a single arm
        forever, since only the arm it keeps picking ever accumulates updates.
        """
        context = np.asarray(context, dtype=float).reshape(-1)
        scores = np.empty(len(self.arms))
        for i, arm in enumerate(self.arms):
            A_inv = np.linalg.inv(self.A[arm])
            theta = A_inv @ self.b[arm]
            mean = float(theta @ context)
            bound = self.alpha * float(np.sqrt(context @ A_inv @ context))
            scores[i] = mean + bound
        max_score = scores.max()
        candidates = [self.arms[i] for i in range(len(self.arms)) if scores[i] >= max_score - 1e-9]
        idx = self._rng.randint(len(candidates))
        return candidates[idx]

    def update(self, arm: float, context: np.ndarray, reward: float) -> None:
        """Updates the chosen arm's statistics with an observed reward.

        Reward convention: +1.0 if the human's eventual disposition agreed with
        the decision SentinelPolicy made using this arm's threshold, -1.0 if the
        human overrode it. This directly implements the survey's "every human
        override decision... is a labeled training signal" (Idea 2).
        """
        context = np.asarray(context, dtype=float).reshape(-1)
        if arm not in self.A:
            raise KeyError(f"Unknown arm: {arm}")
        self.A[arm] += np.outer(context, context)
        self.b[arm] += reward * context
        self.pull_counts[arm] += 1

    def estimated_mean(self, arm: float, context: np.ndarray) -> float:
        context = np.asarray(context, dtype=float).reshape(-1)
        A_inv = np.linalg.inv(self.A[arm])
        theta = A_inv @ self.b[arm]
        return float(theta @ context)

    def to_state_dict(self) -> Dict:
        return {
            "arms": self.arms,
            "context_dim": self.context_dim,
            "alpha": self.alpha,
            "A": {str(a): self.A[a].tolist() for a in self.arms},
            "b": {str(a): self.b[a].tolist() for a in self.arms},
            "pull_counts": {str(a): self.pull_counts[a] for a in self.arms},
        }

    @classmethod
    def from_state_dict(cls, state: Dict) -> "LinUCBBandit":
        bandit = cls(arms=state["arms"], context_dim=state["context_dim"], alpha=state["alpha"])
        for a in bandit.arms:
            bandit.A[a] = np.array(state["A"][str(a)])
            bandit.b[a] = np.array(state["b"][str(a)])
            bandit.pull_counts[a] = state["pull_counts"][str(a)]
        return bandit

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_state_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> Optional["LinUCBBandit"]:
        path = Path(path)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_state_dict(json.load(f))
