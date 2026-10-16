"""SyntheticReviewer: a rule-based simulated human reviewer for offline evaluation.

SentinelPolicy's whole premise is learning from human override decisions, but this
project has no access to real reviewer panels. Per the survey's own idea write-up:
"you won't have real human reviewers at scale... simulating realistic human
override behavior for evaluation is itself a research problem." We do not claim
otherwise: this is a documented synthetic stand-in for evaluation and
demonstration only, calibrated to mirror stated real-world tendencies (humans
readily override rejections on cosmetic/utility issues, rarely override
rejections on financial-calculation risk), not a validated model of real
reviewer behavior.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class SyntheticReviewer:
    # probability a REJECT gets overridden to APPROVE, per category, on a
    # STANDARD/UTILITY-risk module.
    override_probabilities: Dict[str, float] = field(default_factory=lambda: {
        "FINANCIAL_PRECISION": 0.05,
        "NULL_SAFETY": 0.25,
        "RESOURCE_MANAGEMENT": 0.20,
        "EXCEPTION_HANDLING": 0.15,
        "DEPRECATED_API": 0.55,   # mostly cosmetic -> humans usually approve anyway
        "MAGIC_NUMBER": 0.45,
        "UNBOUNDED_LOOP": 0.10,
    })
    # probability an APPROVE gets caught / reversed to REJECT by the human
    catch_probability_standard: float = 0.04
    catch_probability_financial: float = 0.12
    financial_dampener: float = 0.15  # multiplies override prob when module is FINANCIAL
    seed: Optional[int] = None

    def __post_init__(self):
        self._rng = random.Random(self.seed)

    def disposition(self, category: str, policy_decision: str, module_risk_class: str) -> bool:
        """Returns True if the synthetic human approves the change, False if not."""
        if policy_decision in ("REJECT", "ESCALATE"):
            p_override = self.override_probabilities.get(category, 0.15)
            if module_risk_class == "FINANCIAL":
                p_override *= self.financial_dampener
            return self._rng.random() < p_override
        # policy_decision == "APPROVE"
        p_catch = self.catch_probability_financial if module_risk_class == "FINANCIAL" else self.catch_probability_standard
        return not (self._rng.random() < p_catch)
