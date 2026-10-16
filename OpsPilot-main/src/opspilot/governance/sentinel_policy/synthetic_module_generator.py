"""Generates synthetic Java module text with controllable per-category risk density.

Used only for offline evaluation (see `evaluate.py`). Each generated module has a
"true" underlying risk level per category (drawn from a distribution tied to its
risk_class), which is realized as a controllable number of matching snippets.
Because the ground-truth density is known at generation time, evaluation metrics
(override-agreement, escalation rate) are computed against a real, reproducible
signal rather than pure noise.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, Tuple

CATEGORY_SNIPPETS = {
    "FINANCIAL_PRECISION": 'double totalPayAmount = grossPay - taxDue; // financial calc\n',
    "NULL_SAFETY": 'String dept = employee.getRecord().getDept();\n',
    "RESOURCE_MANAGEMENT": 'FileInputStream fis = new FileInputStream(path);\n',
    "EXCEPTION_HANDLING": 'try { process(); } catch (Exception ex) { }\n',
    "DEPRECATED_API": 'Vector legacyBuffer = new Vector();\n',
    "MAGIC_NUMBER": 'if (yearsOfService >= 37) { bonusRate = balance * 0.185; }\n',
    "UNBOUNDED_LOOP": 'while (true) { pollQueue(); }\n',
}

BASE_TEMPLATE = """package com.opspilot.modernized;

import org.springframework.stereotype.Service;

@Service
public class {class_name} {{
    public void process() {{
{body}
    }}
}}
"""


@dataclass
class SyntheticModule:
    module_id: str
    risk_class: str
    code_text: str
    true_density: Dict[str, int]


def _density_for_risk_class(rng: random.Random, risk_class: str) -> Dict[str, Tuple[int, int]]:
    """Returns (min, max) snippet-repeat range per category for this risk class."""
    if risk_class == "FINANCIAL":
        return {
            "FINANCIAL_PRECISION": (0, 4),
            "NULL_SAFETY": (0, 3),
            "RESOURCE_MANAGEMENT": (0, 2),
            "EXCEPTION_HANDLING": (0, 2),
            "DEPRECATED_API": (0, 1),
            "MAGIC_NUMBER": (0, 3),
            "UNBOUNDED_LOOP": (0, 1),
        }
    if risk_class == "UTILITY":
        return {
            "FINANCIAL_PRECISION": (0, 0),
            "NULL_SAFETY": (0, 2),
            "RESOURCE_MANAGEMENT": (0, 2),
            "EXCEPTION_HANDLING": (0, 3),
            "DEPRECATED_API": (0, 4),
            "MAGIC_NUMBER": (0, 2),
            "UNBOUNDED_LOOP": (0, 1),
        }
    # STANDARD
    return {
        "FINANCIAL_PRECISION": (0, 1),
        "NULL_SAFETY": (0, 2),
        "RESOURCE_MANAGEMENT": (0, 2),
        "EXCEPTION_HANDLING": (0, 2),
        "DEPRECATED_API": (0, 2),
        "MAGIC_NUMBER": (0, 2),
        "UNBOUNDED_LOOP": (0, 1),
    }


def generate_synthetic_module(rng: random.Random, module_id: str, risk_class: str) -> SyntheticModule:
    ranges = _density_for_risk_class(rng, risk_class)
    true_density: Dict[str, int] = {}
    body_lines = []
    for category, (lo, hi) in ranges.items():
        count = rng.randint(lo, hi)
        true_density[category] = count
        body_lines.extend([CATEGORY_SNIPPETS[category]] * count)

    rng.shuffle(body_lines)
    # pad with a few benign lines so line-count normalization is realistic
    filler = ["int localCounter = 0;\n"] * rng.randint(5, 15)
    body_lines = filler + body_lines
    body = "        " + "        ".join(body_lines)

    class_name = f"Module{module_id}Service"
    code_text = BASE_TEMPLATE.format(class_name=class_name, body=body)
    return SyntheticModule(module_id=module_id, risk_class=risk_class, code_text=code_text, true_density=true_density)


def generate_module_stream(n_modules: int, seed: int = 42) -> list:
    """Generates a temporally-ordered stream of synthetic modules for a simulated migration."""
    rng = random.Random(seed)
    risk_class_weights = [("FINANCIAL", 0.2), ("UTILITY", 0.35), ("STANDARD", 0.45)]
    modules = []
    for i in range(n_modules):
        r = rng.random()
        cum = 0.0
        chosen = "STANDARD"
        for cls, w in risk_class_weights:
            cum += w
            if r <= cum:
                chosen = cls
                break
        modules.append(generate_synthetic_module(rng, module_id=f"{i:04d}", risk_class=chosen))
    return modules
