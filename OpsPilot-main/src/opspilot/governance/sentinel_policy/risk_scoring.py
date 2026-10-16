"""Soft risk-category scoring for generated Java code.

These signals are deliberately *not* part of the hard denylist
(`opspilot.governance.guardrail_rules`). They are graduated governance concerns --
code smells with real but variable risk -- which is exactly the class of decision
the survey describes as prone to "guardrail stagnation" when policed with a single
fixed threshold: strict enough to be safe on payment logic becomes needlessly
conservative on a low-risk utility module.

Each scorer returns a continuous value in [0, 1]: an approximate density of the
matched pattern, normalized by code length, so a single stray hit in a 300-line
file scores low and a systemic pattern scores high. This is a heuristic, static
proxy for LLM- or human-judged risk -- adequate for driving the adaptive-threshold
mechanism and for reproducible offline evaluation, and documented as such rather
than presented as a validated risk model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Pattern


@dataclass(frozen=True)
class RiskCategory:
    id: str
    description: str
    patterns: List[Pattern] = field(default_factory=list)
    # severity_weight: how much a unit of this risk should count against a module
    # tagged as financial/high-stakes vs. a routine utility module. This encodes
    # the survey's "strict for payment-calculation logic, permissive for lower-risk
    # utility modules" (Sec. VII) directly into the scoring, on top of whatever the
    # bandit later learns.
    financial_severity_weight: float = 1.0
    utility_severity_weight: float = 1.0


RISK_CATEGORIES: Dict[str, RiskCategory] = {
    "FINANCIAL_PRECISION": RiskCategory(
        id="FINANCIAL_PRECISION",
        description="Floating-point (float/double) used for monetary fields instead of BigDecimal.",
        patterns=[
            re.compile(r"\b(?:double|float)\s+\w*(?:pay|amount|amt|salary|tax|total|balance|price|net)\w*",
                       re.IGNORECASE),
        ],
        financial_severity_weight=2.5,
        utility_severity_weight=0.5,
    ),
    "NULL_SAFETY": RiskCategory(
        id="NULL_SAFETY",
        description="Chained field/method access with no adjacent null guard.",
        patterns=[
            re.compile(r"\b\w+\.get\w+\(\)\.\w+"),
        ],
        financial_severity_weight=1.5,
        utility_severity_weight=1.0,
    ),
    "RESOURCE_MANAGEMENT": RiskCategory(
        id="RESOURCE_MANAGEMENT",
        description="File/stream/connection opened without try-with-resources.",
        patterns=[
            re.compile(r"new\s+(?:FileInputStream|FileOutputStream|FileReader|FileWriter|Socket|Connection)\s*\("),
        ],
        financial_severity_weight=1.5,
        utility_severity_weight=1.0,
    ),
    "EXCEPTION_HANDLING": RiskCategory(
        id="EXCEPTION_HANDLING",
        description="Broad or empty catch block that silently swallows exceptions.",
        patterns=[
            re.compile(r"catch\s*\(\s*Exception\s+\w+\s*\)\s*\{\s*\}"),
            re.compile(r"catch\s*\(\s*Exception\s+\w+\s*\)\s*\{\s*(?://[^\n]*)?\s*\}"),
        ],
        financial_severity_weight=2.0,
        utility_severity_weight=0.6,
    ),
    "DEPRECATED_API": RiskCategory(
        id="DEPRECATED_API",
        description="Use of a legacy/deprecated Java API (java.util.Date, Vector, Hashtable).",
        patterns=[
            re.compile(r"\bnew\s+(?:Date|Vector|Hashtable|StringBuffer)\s*\("),
        ],
        financial_severity_weight=1.0,
        utility_severity_weight=0.6,
    ),
    "MAGIC_NUMBER": RiskCategory(
        id="MAGIC_NUMBER",
        description="Raw numeric literal embedded directly in conditional/compute logic.",
        patterns=[
            re.compile(r"(?:if|while)\s*\([^)]*[<>=]=?\s*\d{2,}"),
            re.compile(r"[a-zA-Z_]\w*\s*[*/+-]\s*0\.\d+\b"),
        ],
        financial_severity_weight=1.5,
        utility_severity_weight=0.5,
    ),
    "UNBOUNDED_LOOP": RiskCategory(
        id="UNBOUNDED_LOOP",
        description="Loop with no visibly bounded terminating condition.",
        patterns=[
            re.compile(r"while\s*\(\s*true\s*\)"),
            re.compile(r"for\s*\(\s*;\s*;\s*\)"),
        ],
        financial_severity_weight=1.2,
        utility_severity_weight=0.8,
    ),
}


def _density(text: str, pattern: Pattern) -> float:
    """Match count normalized per 100 lines, then squashed into [0, 1]."""
    lines = max(text.count("\n") + 1, 1)
    hits = len(pattern.findall(text))
    per_100_lines = hits / lines * 100.0
    # Saturating curve calibrated so an isolated, incidental hit registers as low
    # risk (a single stray pattern in a ~20-line method -> ~0.16) while a
    # systemic pattern (several hits per method) saturates toward 1.0.
    return 1.0 - pow(2.718281828, -per_100_lines / 18.0)


def score_soft_risks(code_text: str, module_risk_class: str = "STANDARD") -> Dict[str, float]:
    """Scores `code_text` against every soft risk category.

    Args:
        code_text: generated source to evaluate.
        module_risk_class: one of "FINANCIAL", "UTILITY", "STANDARD". Used only to
            select the severity weight; the *density* score itself is
            weight-independent so the raw signal is preserved for logging.

    Returns:
        Mapping of category id -> weighted risk score in roughly [0, ~2.5].
    """
    weight_key = {
        "FINANCIAL": "financial_severity_weight",
        "UTILITY": "utility_severity_weight",
    }.get(module_risk_class, None)

    scores: Dict[str, float] = {}
    for cat_id, category in RISK_CATEGORIES.items():
        raw = max((_density(code_text, p) for p in category.patterns), default=0.0)
        weight = getattr(category, weight_key) if weight_key else 1.0
        scores[cat_id] = round(raw * weight, 4)
    return scores
