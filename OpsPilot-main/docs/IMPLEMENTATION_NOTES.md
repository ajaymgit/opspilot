# Implementation Notes: OpsPilot+ Research Extensions

This document is the advisor's-eye view of what was built, what was
deliberately left out, and why -- written so you (and anyone reviewing this
project, including a course instructor or a paper reviewer) can see the
reasoning, not just the code.

## 1. What got implemented, and why these three

You gave me ten candidate ideas: four sketched at gap-analysis depth (G7
TopoSelect, G9 AdaptGuard, G10 CheckpointOptimizer, G11 TierRoute) and three
fleshed out to full research-proposal depth (Idea 2 SentinelPolicy, Idea 8
RefineRL, Idea 4 RepoMind). You gave me authority to decide what belongs in
the implementation. Here's the actual reasoning.

**Implemented: SentinelPolicy, RefineRL, RepoMind.** These three were chosen
together, not independently, because they satisfy the same three criteria as a
set:

1. **They target a gap the survey names explicitly**, not a gap I inferred.
   SentinelPolicy closes G9 (guardrail stagnation, Table I's own stated
   "Primary Limitation" for the AI Guardrails framework). RefineRL closes the
   fixed-iteration-budget gap named directly in Section VI ("motivating an
   adaptive rather than fixed iteration budget B"). RepoMind closes the
   repo-scale memory gap Section V-A admits is "a target design goal... rather
   than a proven one."
2. **They compose without contradicting each other or the base architecture.**
   All three are *additive* layers on the existing four-phase pipeline, not
   replacements for it, and none of them touches the four non-negotiable
   constraints in `ARCHITECTURE.md` (see Section 3 below for the constraint-
   by-constraint check).
3. **They are evaluable without infrastructure this project doesn't have.**
   No real HITL reviewer panel, no hosted vector DB, no Postgres/Kafka/K8s
   deployment. Each idea's own write-up already anticipates this ("simulate a
   migration run... with a rule-based synthetic reviewer", "a synthetic
   multi-module COBOL mini-repository... built specifically so you control the
   ground-truth dependency graph") -- so building a rigorous *offline*,
   simulation-based evaluation for each was the intended scope, not a
   compromise.

**Not implemented: G7 (TopoSelect), G10 (CheckpointOptimizer), G11 (TierRoute),
and the separate "AdaptGuard" sketch under G9.**

- **G7 / TopoSelect** directly conflicts with this codebase's **Constraint 2:
  No Flat GroupChat**. TopoSelect's entire premise is choosing *among*
  topologies (2-agent, sequential, nested, group-chat) per task. This
  repository has already made an architectural commitment to a single,
  deterministic Python control plane specifically to avoid the
  non-determinism a flexible-topology system would reintroduce. Implementing
  TopoSelect here would mean arguing against the base architecture's own
  design constraint inside the same codebase that enforces it. If you want
  this direction, it belongs in a *different* reference architecture, or as a
  documented proposal to revisit Constraint 2 -- not bolted on quietly.
- **AdaptGuard (the G9 sketch)** is the same idea as Idea 2 (SentinelPolicy),
  described at lower fidelity. Idea 2's write-up is the fully-specified
  version of the same mechanism (per-category threshold + contextual bandit +
  a non-learned hard-constraint backstop). Implementing both would mean
  building the same system twice under two names. SentinelPolicy is the
  canonical implementation; where AdaptGuard's sketch used slightly different
  language ("constrained update... thresholds can auto-tighten but require
  human sign-off to loosen"), that specific asymmetric-update idea is called
  out as a documented **future extension** in Section 4 below, since it's a
  genuine refinement SentinelPolicy doesn't currently implement.
- **G10 / CheckpointOptimizer** and **G11 / TierRoute** are both reasonable,
  legitimate research directions, and neither was rejected on quality grounds.
  They were cut for scope: implementing three ideas rigorously (real code,
  real bugs found and fixed, real synthetic evaluations with honest results)
  is already a substantial project. Adding a fourth and fifth would have meant
  either shipping something shallower across the board, or not shipping the
  paper. If you want to extend this project next, G11 (TierRoute) is the
  better second choice of the two: it's evaluable with the same kind of
  offline simulation methodology already built out here (log a cost/accuracy
  tradeoff per model tier, fit a router, compare against an all-frontier
  baseline), whereas G10 (CheckpointOptimizer) really does need at least
  approximate real reviewer-time data to be more than a guess.

## 2. What "implemented" actually means here

Every one of the three subsystems is:

- **Real, runnable code** in `src/opspilot/{governance/sentinel_policy,
  execution/refine_rl, memory}/`, not pseudocode or a design doc.
- **Unit-tested** (`tests/test_sentinel_policy.py`, `tests/test_refine_rl.py`,
  `tests/test_repomind.py` -- 43 tests across the three, all passing alongside
  the original 16-test base suite).
- **Wired into the real pipeline**, behind feature flags in
  `config/llm_config.yaml` (`extensions.sentinel_policy.enabled`,
  `extensions.refine_rl.enabled`, `extensions.repo_mind.enabled`, all default
  `false` so the base pipeline's behavior and all its original tests are
  byte-for-byte unchanged unless you opt in). See `master_orchestrator.py`'s
  `_repo_mind_ingest_phase1`, `_refine_rl_predict_budget`,
  `_sentinel_policy_evaluate`, and `_repo_mind_record_and_propagate` for the
  integration points.
- **Evaluated with real experiments that actually ran**, not invented numbers.
  Every figure in `docs/EVALUATION_RESULTS.md` was produced by running the
  evaluation harnesses in this repository (`opspilot.governance.
  sentinel_policy.evaluate`, `opspilot.execution.refine_rl.evaluate`,
  `opspilot.memory.evaluate_propagation` / `evaluate_semantic_recall`), which
  you can re-run yourself with `python -m opspilot.cli evaluate-extensions
  all`.

None of the three are the full 3-4 month, production-service version their
own write-ups describe (Postgres decision logs, a Recharts dashboard, Kafka
propagation queues, K8s deployment). That version was never in scope for this
project. What's here is the *mechanism* -- the actual algorithm, correctly
implemented, integrated into the real pipeline, and evaluated honestly against
the right baselines -- which is what a paper needs to make its contribution
claim, and what an instructor needs to see to know the idea was actually
understood and not just described.

## 3. Architectural fit: the four non-negotiable constraints

Every extension was checked against `ARCHITECTURE.md`'s four constraints
before being wired in:

| Constraint | SentinelPolicy | RefineRL | RepoMind |
|---|---|---|---|
| **1. Deterministic static analysis first** | Soft-risk scoring is regex/heuristic, not LLM-judged (`risk_scoring.py`) | Features come from the existing `analysis_output` / dependency graph, never re-derived by an LLM | Graph ingestion reuses `DependencyGraphBuilder`'s deterministic output |
| **2. No flat GroupChat** | Operates after the loop, no new agents/topology | Wraps the loop's iteration bound, no new agents | Operates around the loop (pre/post), no new agents |
| **3. Strict Coder/Verifier inner-loop isolation** | Doesn't touch the inner loop at all | Governs *when the loop stops*, not who's in it | Doesn't touch the inner loop; propagation schedules separate re-verification runs |
| **4. Deterministic Python guardrails** | The *judgment* (risk scoring, hard-constraint check) stays 100% deterministic Python; only the *acceptance threshold* is learned, and it governs a new soft-risk category, never the existing hard denylist | N/A (not a governance mechanism) | N/A (not a governance mechanism) |

The one worth dwelling on is Constraint 4, because "adaptive" and
"deterministic guardrails" sound like they're in tension. They're not, and
the separation is deliberate:
`opspilot.governance.sentinel_policy.policy_agent.check_hard_constraints`
calls the *exact same* `guardrail_rules.get_all_prohibited_rules()` the base
pipeline's interceptor uses -- SentinelPolicy cannot drift from it, and
short-circuits before the bandit is ever consulted (see
`test_hard_constraint_never_learnable` in `tests/test_sentinel_policy.py`).
What's learned is a *second, separate* layer of graduated code-quality risk
categories (financial-precision, null-safety, resource-management, etc.) that
were never part of the hard denylist to begin with. No LLM judges safety
anywhere in this subsystem, and no learned threshold can ever suppress or
weaken the original interceptor.

## 4. Honest results, including where they're not clean wins

In the spirit of the survey's own epistemic style (it flags its own 93%
figure as "one team's result, not an independently validated finding," and
explicitly separates genuine within-study comparisons from cross-study ones),
here's the same treatment for this implementation's own results:

- **SentinelPolicy** is a clean, dramatic result on its own synthetic
  benchmark: a 92-97% relative reduction in "wasted escalations" (flagged,
  then human-overridden) versus a static uniform threshold, with the hard-
  constraint catch rate staying at 100% throughout. This is the strongest
  result of the three, largely because the mechanism (learn a per-category
  threshold from a stationary reward signal) is a good match for a small
  multi-armed-bandit formulation, which converges reliably.
- **RefineRL** is an honest, more nuanced result: it lands *near*, but not
  strictly on, the achievable cost/convergence frontier traced by sweeping a
  single fixed budget across the same synthetic population (see
  `docs/results/refine_rl/frontier.png`). A well-tuned single fixed budget is
  competitive with RefineRL's aggregate numbers in this experiment. What
  RefineRL actually buys you is not implemented here as "always better than
  any fixed choice" -- it's per-module adaptivity without needing to already
  know the right fixed value for a given (and potentially shifting) module
  population, plus a meaningfully better outcome specifically on genuinely
  unconvergeable modules (avg. ~8.4 iterations spent vs. a fixed-high
  baseline's 12, since the plateau detector stops it early) and on
  conservatively-low fixed budgets (dramatically fewer premature escalations).
  I chose not to tune the synthetic reward model further to force a cleaner
  aggregate win, because that would be curve-fitting the *evaluation* to flatter
  the *result*, which is a worse failure mode than reporting a real trade-off.
- **RepoMind** is a clean result for change propagation specifically (100%
  recall of truly-impacted modules with a 67-69% reduction in re-verification
  scope versus "verify everything"), by construction: the propagation
  mechanism is a graph traversal, and a graph traversal that walks the same
  edges the ground truth was defined from will always be sound. The
  interesting empirical content is the *scope reduction* number, not the
  recall number. Semantic memory retrieval (precision@5 = 1.0 vs. a 0.2 random
  baseline) is a genuinely easier evaluation than a production system would
  face, because the synthetic corpus uses topically distinct vocabulary by
  construction -- see the caveat in `docs/EVALUATION_RESULTS.md`.

## 5. Real bugs found and fixed during development (kept here on purpose)

Three of these are worth recording because they're the kind of mistake that
produces a misleadingly clean-looking wrong result if you don't catch them --
which is exactly the failure mode this whole implementation's design
philosophy (borrowed from the survey's own rigor) is trying to avoid:

1. **SentinelPolicy's threshold ladder had its lowest arm equal to the
   escalation margin**, meaning even genuinely clean code (risk score = 0)
   could never register as APPROVE at that arm. Fixed by keeping the lowest
   arm comfortably above the margin (`policy_agent.DEFAULT_ARMS`), with a
   regression test (`test_default_arms_never_flag_a_clean_module_regardless_of_arm`).
2. **The bandit reward signal was being aggregated across all seven risk
   categories into a single AND'd boolean** before being recorded, so one
   flagged category in a module could poison the learning signal for six
   well-calibrated ones. This was the actual root cause of an early
   (wrong-looking, and it *was* wrong) result showing the bandit performing
   *worse* than a static baseline. Fixed by making `record_human_disposition`
   accept a per-category disposition mapping
   (`test_reward_isolated_per_category_not_aggregated` is the regression
   test).
3. **RefineRL's synthetic trajectory generator could let injected noise round
   a failure count down to zero before the trajectory's own declared "true"
   convergence iteration**, making the ground truth internally inconsistent
   with the observable data derived from it. Fixed by clamping noise so a
   trajectory never "accidentally" converges early
   (`test_simulated_trajectory_never_reports_convergence_before_true_iteration`).

None of these were cosmetic. Each one, left in place, would have produced a
plausible-looking but wrong number in `docs/EVALUATION_RESULTS.md`.

## 6. If you extend this project next

In rough order of how well they fit what's already here:

1. **Asymmetric threshold updates for SentinelPolicy** (auto-tighten freely,
   require human sign-off to loosen past some point) -- the AdaptGuard
   refinement noted in Section 1, and a natural extension of the existing
   `ThompsonThresholdBandit`.
2. **G11 / TierRoute** -- same offline-simulation evaluation methodology as
   RefineRL would transfer directly (log cost/accuracy per model tier per
   subtask, fit a router, compare a cost-vs-accuracy Pareto curve against an
   all-frontier baseline).
3. **Real embeddings for RepoMind's semantic memory**, swapping the TF-IDF
   backend for a real embedding API, once this project has network access to
   one -- the interface (`SemanticMemory.search`) is already backend-agnostic.
4. **G10 / CheckpointOptimizer** -- worth doing once you have even
   approximate real reviewer-time data; a purely synthetic cost model for this
   one specifically risks being a guess dressed up as a Pareto curve.
