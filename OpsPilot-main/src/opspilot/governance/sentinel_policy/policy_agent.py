"""GuardrailPolicyAgent: composes the deterministic hard-constraint layer with the
adaptive, bandit-learned soft-risk-category layer.

Decision semantics per category, given risk score `s` and the bandit-selected
threshold `t` for that category's (category, module_risk_class) group:

    s <  t - margin   -> APPROVE   (comfortably under threshold)
    s >  t + margin   -> REJECT    (comfortably over threshold)
    otherwise         -> ESCALATE  (near the boundary: routed to HITL, per the
                                     survey's own HITL-as-first-class-component
                                     principle, Sec. V-A)

The overall decision for a proposed change is the most conservative across all
scored categories: any REJECT dominates; else any ESCALATE dominates; else
APPROVE. Hard-constraint violations short-circuit everything and are never
routed through the bandit -- this is the non-negotiable backstop the survey's
own Section VII caveat ("tempered against the safety risks") requires.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from opspilot.governance.guardrail_rules import get_all_prohibited_rules
from opspilot.governance.sentinel_policy.risk_scoring import RISK_CATEGORIES, score_soft_risks
from opspilot.governance.sentinel_policy.thompson_bandit import ThompsonThresholdBandit

CATEGORY_IDS = list(RISK_CATEGORIES.keys())
# Smallest arm is kept comfortably above ESCALATION_MARGIN so a clean module
# (risk score == 0 in every category) is always approvable regardless of which
# arm is currently selected -- otherwise the lowest rung of the threshold
# ladder would flag entirely benign code by construction.
DEFAULT_ARMS = [0.10, 0.15, 0.20, 0.28, 0.36, 0.45, 0.55, 0.68, 0.85]
ESCALATION_MARGIN = 0.05


@dataclass
class ModuleContext:
    module_id: str
    risk_class: str = "STANDARD"  # "FINANCIAL" | "UTILITY" | "STANDARD"
    complexity: float = 0.5       # normalized 0..1 (e.g. cyclomatic complexity / 30), logged only


@dataclass
class CategoryDecision:
    category: str
    score: float
    threshold: float
    decision: str  # APPROVE | REJECT | ESCALATE
    context_vector: List[float] = field(default_factory=list)  # unused by default backend; kept for LinUCB interop


@dataclass
class GuardrailDecision:
    decision_id: str
    overall_decision: str  # APPROVE | REJECT | ESCALATE | HARD_VIOLATION
    hard_violation: Optional[Dict] = None
    category_decisions: List[CategoryDecision] = field(default_factory=list)
    module_id: str = ""
    module_risk_class: str = "STANDARD"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


def _build_context_vector(category_id: str, score: float, module_context: ModuleContext):
    """Retained for interop with the LinUCB backend in `bandit.py`; unused by the
    default Thompson-sampling backend, which conditions on (category, risk_class)
    directly rather than a shared continuous context vector."""
    import numpy as np
    vec = np.zeros(len(CATEGORY_IDS) + 3)
    vec[CATEGORY_IDS.index(category_id)] = 1.0
    vec[len(CATEGORY_IDS)] = score
    vec[len(CATEGORY_IDS) + 1] = module_context.complexity
    vec[len(CATEGORY_IDS) + 2] = 1.0 if module_context.risk_class == "FINANCIAL" else 0.0
    return vec


def check_hard_constraints(code_text: str) -> Optional[Dict]:
    """Deterministic, non-learned check against the canonical denylist.

    Re-uses `guardrail_rules.get_all_prohibited_rules()` -- the single source of
    truth for hard constraints -- rather than duplicating the rule set, so
    SentinelPolicy can never drift from the base guardrail interceptor used by
    the main pipeline (`guardrail_interceptor.py`).
    """
    for rule in get_all_prohibited_rules():
        pattern = rule["pattern"]
        matched = bool(re.search(pattern, code_text, re.IGNORECASE)) if rule.get("is_regex") else pattern in code_text
        if matched:
            return {"rule_id": rule["id"], "category": rule["category"], "description": rule["description"]}
    return None


class GuardrailPolicyAgent:
    """Adaptive governance layer. Never overrides hard constraints; only governs
    the soft-risk-category layer via per-(category, risk_class) learned thresholds."""

    def __init__(
        self,
        bandit: Optional[ThompsonThresholdBandit] = None,
        arms: Optional[List[float]] = None,
        seed: Optional[int] = None,
        decision_log_path: Optional[Path] = None,
    ):
        self.bandit = bandit or ThompsonThresholdBandit(arms=arms or DEFAULT_ARMS, seed=seed)
        self.decision_log_path = Path(decision_log_path) if decision_log_path else None
        self._pending: Dict[str, GuardrailDecision] = {}
        self._frozen = False

    def freeze(self) -> None:
        """Switches the agent to pure exploitation: for each (category,
        risk_class) group, always uses the arm with the highest posterior mean
        rather than Thompson-sampling from the posterior. Used to evaluate the
        *learned policy* on held-out data, separated from ongoing exploration."""
        self._frozen = True

    def unfreeze(self) -> None:
        self._frozen = False

    def evaluate(self, code_text: str, module_context: ModuleContext) -> GuardrailDecision:
        hard = check_hard_constraints(code_text)
        decision_id = str(uuid.uuid4())

        if hard is not None:
            decision = GuardrailDecision(
                decision_id=decision_id,
                overall_decision="HARD_VIOLATION",
                hard_violation=hard,
                module_id=module_context.module_id,
                module_risk_class=module_context.risk_class,
            )
            self._log(decision)
            return decision

        scores = score_soft_risks(code_text, module_context.risk_class)
        category_decisions: List[CategoryDecision] = []
        for category_id, score in scores.items():
            if self._frozen:
                threshold = self.bandit.best_arm_by_posterior_mean(category_id, module_context.risk_class)
            else:
                threshold = self.bandit.select_arm(category_id, module_context.risk_class)

            if score < threshold - ESCALATION_MARGIN:
                cat_decision = "APPROVE"
            elif score > threshold + ESCALATION_MARGIN:
                cat_decision = "REJECT"
            else:
                cat_decision = "ESCALATE"

            category_decisions.append(CategoryDecision(
                category=category_id, score=score, threshold=threshold, decision=cat_decision,
            ))

        if any(c.decision == "REJECT" for c in category_decisions):
            overall = "REJECT"
        elif any(c.decision == "ESCALATE" for c in category_decisions):
            overall = "ESCALATE"
        else:
            overall = "APPROVE"

        decision = GuardrailDecision(
            decision_id=decision_id,
            overall_decision=overall,
            category_decisions=category_decisions,
            module_id=module_context.module_id,
            module_risk_class=module_context.risk_class,
        )
        self._pending[decision_id] = decision
        self._log(decision)
        return decision

    def record_human_disposition(self, decision_id: str, category_dispositions: Dict[str, bool]) -> None:
        """Feeds each category's human disposition back into the bandit as an
        independent reward signal.

        `category_dispositions` maps category_id -> whether the human approved
        the proposed change *with respect to that specific category's flag*.
        This must be per-category, not one aggregate yes/no for the whole
        module: collapsing seven independent signals into a single AND before
        recording would let one unrelated flagged category poison the reward
        for six well-calibrated ones. Success (reward=1) if the policy's call
        for that category agreed with the human's disposition for that
        category, failure (reward=0) otherwise. Hard-violation decisions never
        reach this method (they are never routed to the bandit). This directly
        implements the survey's "every human override decision... is a labeled
        training signal" (Idea 2), at the granularity the signal actually
        exists at.
        """
        decision = self._pending.pop(decision_id, None)
        if decision is None:
            return
        for cat in decision.category_decisions:
            human_approved = category_dispositions.get(cat.category)
            if human_approved is None:
                continue
            policy_said_approve = cat.decision == "APPROVE"
            agreed = policy_said_approve == human_approved
            self.bandit.update(cat.category, decision.module_risk_class, cat.threshold, success=agreed)

    def _log(self, decision: GuardrailDecision) -> None:
        if not self.decision_log_path:
            return
        self.decision_log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "decision_id": decision.decision_id,
            "module_id": decision.module_id,
            "module_risk_class": decision.module_risk_class,
            "overall_decision": decision.overall_decision,
            "hard_violation": decision.hard_violation,
            "categories": [
                {"category": c.category, "score": c.score, "threshold": c.threshold, "decision": c.decision}
                for c in decision.category_decisions
            ],
            "timestamp": decision.timestamp,
        }
        logs = []
        if self.decision_log_path.exists():
            try:
                logs = json.loads(self.decision_log_path.read_text(encoding="utf-8"))
            except Exception:
                logs = []
        logs.append(entry)
        self.decision_log_path.write_text(json.dumps(logs, indent=2), encoding="utf-8")
