"""Per-(risk-category, module-risk-class) Thompson-sampling threshold bandit.

The idea write-up names two acceptable bandit formulations: "LinUCB or a
Thompson-sampling bandit over (module-risk-category, threshold)". This module
implements the latter and is SentinelPolicy's *default* mechanism.

Why Thompson sampling here rather than the shared-context LinUCB in `bandit.py`:
the reward distribution for a given (category, risk_class) pair is close to
stationary in this problem -- it is governed by a roughly fixed human-override
tendency for that category, not by a continuously-varying function of the risk
score itself. That makes it a small set of near-classical multi-armed bandit
problems (one per group, ~9 arms each), not a problem that benefits from
cross-context generalization. A Beta-Bernoulli Thompson-sampling bandit is the
textbook-appropriate tool for that setting and converges with far less data and
far less tuning sensitivity than a 10-dimensional shared-context LinUCB
regression would for the same number of observations. `bandit.py`'s LinUCB
implementation is kept as a documented, usable alternative (e.g. if a future
version wants the threshold to vary continuously with a richer feature set),
but is not the mechanism SentinelPolicy uses by default.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class BetaArm:
    alpha: float = 1.0
    beta: float = 1.0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def pulls(self) -> float:
        return self.alpha + self.beta - 2.0


class ThompsonThresholdBandit:
    """Beta-Bernoulli Thompson sampling over a discrete threshold ladder,
    maintained independently per (risk_category, module_risk_class) group."""

    def __init__(self, arms: List[float], seed: Optional[int] = None):
        if not arms:
            raise ValueError("ThompsonThresholdBandit requires at least one arm.")
        self.arms = list(arms)
        self.groups: Dict[Tuple[str, str], Dict[float, BetaArm]] = {}
        self._rng = random.Random(seed)

    def _group(self, category: str, risk_class: str) -> Dict[float, BetaArm]:
        key = (category, risk_class)
        if key not in self.groups:
            self.groups[key] = {a: BetaArm() for a in self.arms}
        return self.groups[key]

    def select_arm(self, category: str, risk_class: str) -> float:
        """Samples a success probability per arm from its current posterior and
        returns the arm with the highest sample (standard Thompson sampling)."""
        group = self._group(category, risk_class)
        best_arm, best_sample = self.arms[0], -1.0
        for arm in self.arms:
            beta_arm = group[arm]
            sample = self._rng.betavariate(beta_arm.alpha, beta_arm.beta)
            if sample > best_sample:
                best_sample, best_arm = sample, arm
        return best_arm

    def update(self, category: str, risk_class: str, arm: float, success: bool) -> None:
        beta_arm = self._group(category, risk_class)[arm]
        if success:
            beta_arm.alpha += 1.0
        else:
            beta_arm.beta += 1.0

    def posterior_mean(self, category: str, risk_class: str, arm: float) -> float:
        return self._group(category, risk_class)[arm].mean

    def best_arm_by_posterior_mean(self, category: str, risk_class: str) -> float:
        group = self._group(category, risk_class)
        return max(self.arms, key=lambda a: group[a].mean)

    def to_state_dict(self) -> Dict:
        return {
            "arms": self.arms,
            "groups": {
                f"{cat}|{cls}": {str(a): {"alpha": g[a].alpha, "beta": g[a].beta} for a in self.arms}
                for (cat, cls), g in self.groups.items()
            },
        }

    @classmethod
    def from_state_dict(cls, state: Dict, seed: Optional[int] = None) -> "ThompsonThresholdBandit":
        bandit = cls(arms=state["arms"], seed=seed)
        for key, arm_states in state["groups"].items():
            cat, cls_name = key.split("|", 1)
            group = bandit._group(cat, cls_name)
            for arm_str, vals in arm_states.items():
                arm = float(arm_str)
                group[arm] = BetaArm(alpha=vals["alpha"], beta=vals["beta"])
        return bandit

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_state_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Optional["ThompsonThresholdBandit"]:
        path = Path(path)
        if not path.exists():
            return None
        return cls.from_state_dict(json.loads(path.read_text(encoding="utf-8")))
