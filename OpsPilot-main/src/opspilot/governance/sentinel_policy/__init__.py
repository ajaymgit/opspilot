"""SentinelPolicy: risk-adaptive guardrail thresholds via contextual-bandit learning.

Implements the "AdaptGuard / SentinelPolicy" research direction identified in the
survey (Section VII, "Guardrail stagnation... adaptive, sensitivity-based guardrail
thresholds... via policy-gradient methods", and Table I's Primary Limitation for the
AI Guardrails framework: "Overly strict rules cause guardrail stagnation").

Design summary
---------------
Every surveyed guardrail layer (Mishra's deterministic-bounds model, AutoGen's
safeguard agent, MetaGPT's SOP gates) uses static, uniform accept/reject thresholds.
SentinelPolicy adds a *second*, learned layer that sits alongside -- never inside --
the existing deterministic denylist (`opspilot.governance.guardrail_rules`):

    Hard-Constraint Layer (unchanged, non-negotiable, deterministic)
        -> opspilot.governance.guardrail_rules.PROHIBITED_PATTERNS
        -> credential leaks, destructive DDL, command injection, etc.
        -> NEVER touched by the bandit, per the survey's own caveat that any
           relaxation must be "tempered against the safety risks" (Sec. VII).

    Soft Risk-Category Layer (new, adaptive)
        -> graduated code-quality/governance risk signals (financial-precision,
           null-safety, resource management, exception handling, deprecated APIs,
           magic numbers, unbounded loops) that are legitimate governance concerns
           but not absolute denylist violations.
        -> Each risk category has a per-category acceptance threshold learned
           online from logged human-override outcomes via a LinUCB contextual
           bandit (Li et al., 2010).

This subpackage is intentionally decoupled from the base pipeline: importing it
has no effect on `MasterOrchestrator` unless explicitly wired in via
`governance.sentinel.enabled: true` in `config/llm_config.yaml`.
"""

from opspilot.governance.sentinel_policy.policy_agent import GuardrailPolicyAgent
from opspilot.governance.sentinel_policy.bandit import LinUCBBandit
from opspilot.governance.sentinel_policy.thompson_bandit import ThompsonThresholdBandit
from opspilot.governance.sentinel_policy.risk_scoring import score_soft_risks, RISK_CATEGORIES
from opspilot.governance.sentinel_policy.synthetic_reviewer import SyntheticReviewer

__all__ = [
    "GuardrailPolicyAgent",
    "LinUCBBandit",
    "ThompsonThresholdBandit",
    "score_soft_risks",
    "RISK_CATEGORIES",
    "SyntheticReviewer",
]
