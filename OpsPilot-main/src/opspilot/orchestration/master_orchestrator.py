"""Master Orchestrator Control Plane for OpsPilot.

Drives the modernization pipeline deterministically in plain Python. Triggers isolated
sub-chats for specific phases and explicitly avoids monolithic group-chats.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import yaml
except ImportError:
    yaml = None

from autogen import UserProxyAgent

from opspilot.orchestration.pipeline_state import PipelineState, PipelineResult
from opspilot.analysis.parsers.cobol_parser import parse_cobol_file
from opspilot.analysis.parsers.plsql_parser import parse_plsql_file
from opspilot.analysis.dependency_graph import DependencyGraphBuilder
from opspilot.analysis.analysis_agent import create_analysis_agent
from opspilot.execution.coder_agent import create_coder_agent
from opspilot.execution.verifier_agent import create_verifier_agent
from opspilot.execution.self_refine_loop import run_self_refine_loop
from opspilot.governance.guardrail_interceptor import register_guardrail_interceptor
from opspilot.utils.json_schema import validate_analysis_output
from opspilot.utils.logging_utils import get_logger, log_phase_transition

# OpsPilot+ research extensions -- all optional, imported lazily where used so
# a base-pipeline-only install/test run never pays for or depends on them.


def load_config(config_path: Path) -> Dict[str, Any]:
    """Loads configuration matrix from YAML file."""
    default_cfg = {
        "llm": {"model": "gpt-4o", "temperature": 0.2},
        "pipeline": {"phase3_iteration_budget": 10, "sandbox": {"use_docker": False, "work_dir": "workspace"}}
    }
    if not config_path.exists():
        return default_cfg
    if yaml is not None:
        with open(config_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            return loaded if loaded else default_cfg
    return default_cfg


class MasterOrchestrator:
    """Sequential control plane managing the modernization pipeline execution."""

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            config_path = Path("config/llm_config.yaml")
        self.config = load_config(config_path)
        self.logger = get_logger("opspilot.orchestrator", log_file=Path("workspace/pipeline.log"))

        # UserProxyAgent controller
        self.orchestrator_agent = UserProxyAgent(
            name="Orchestrator",
            human_input_mode="NEVER",
            code_execution_config=False
        )

        self.extensions_config = self.config.get("extensions", {})

    # -- OpsPilot+ extensions (all no-ops unless enabled in config) ---------

    def _repo_mind_ingest_phase1(self, state: "PipelineState") -> None:
        """After Phase 1's dependency graph is built, merge it into the
        persistent, repo-scale RepoDependencyGraph (Idea 4)."""
        cfg = self.extensions_config.get("repo_mind", {})
        if not cfg.get("enabled"):
            return
        from opspilot.memory.repo_dependency_graph import RepoDependencyGraph

        graph_path = Path(cfg.get("dependency_graph_file", "workspace/repo_dependency_graph.json"))
        repo_graph = RepoDependencyGraph.load(graph_path) or RepoDependencyGraph()
        repo_graph.ingest_module_graph(state.dependency_graph)
        repo_graph.save(graph_path)
        self.logger.info(f"[RepoMind] merged module into repo graph ({repo_graph.node_count} nodes total)")

    def _refine_rl_predict_budget(self, state: "PipelineState", default_budget: int) -> int:
        """Predicts a per-module iteration budget from Discovery-time features,
        training on whatever real (features -> actual iterations) history has
        accumulated across previous runs (Idea 8). Falls back to
        `default_budget` (the static config value) when the extension is
        disabled or there isn't enough history to train on yet."""
        cfg = self.extensions_config.get("refine_rl", {})
        if not cfg.get("enabled"):
            return default_budget
        from opspilot.execution.refine_rl.module_features import extract_module_features
        from opspilot.execution.refine_rl.predictor import IterationBudgetPredictor

        history_path = Path(cfg.get("history_file", "workspace/refine_rl_history.json"))
        history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []

        predictor = IterationBudgetPredictor()
        min_samples = cfg.get("min_training_samples", 20)
        if len(history) >= min_samples:
            from opspilot.execution.refine_rl.module_features import ModuleFeatures
            feats = [ModuleFeatures(**h["features"]) for h in history]
            targets = [h["actual_iterations"] for h in history]
            predictor.fit(feats, targets)

        features = extract_module_features(state.analysis_output, state.dependency_graph)
        predicted = predictor.predict(features)
        self.logger.info(f"[RefineRL] predicted iteration budget={predicted} "
                          f"(trained={predictor.is_trained}, history_size={len(history)})")
        state.refine_rl_predicted_budget = predicted
        return predicted

    def _refine_rl_log_outcome(self, state: "PipelineState") -> None:
        cfg = self.extensions_config.get("refine_rl", {})
        if not cfg.get("enabled"):
            return
        if state.guardrail_status == "VIOLATION_DETECTED":
            # a guardrail violation reflects a safety stop, not refinement
            # difficulty -- logging its iteration count would inject noise
            # unrelated to what the predictor is trying to learn.
            return
        from opspilot.execution.refine_rl.module_features import extract_module_features

        history_path = Path(cfg.get("history_file", "workspace/refine_rl_history.json"))
        history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
        features = extract_module_features(state.analysis_output, state.dependency_graph)
        history.append({"features": features.__dict__, "actual_iterations": state.iteration_count})
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")

    def _sentinel_policy_evaluate(self, state: "PipelineState") -> None:
        """Runs the adaptive soft-risk-category guardrail layer over the
        generated code (Idea 2). Informational by default (logs the decision
        without altering pipeline pass/fail); set
        extensions.sentinel_policy.enforce: true to let a REJECT also fail the
        pipeline. Never replaces or weakens the hard-constraint guardrail
        interceptor already registered on the Verifier."""
        cfg = self.extensions_config.get("sentinel_policy", {})
        if not cfg.get("enabled") or not state.generated_code:
            return
        from opspilot.governance.sentinel_policy.policy_agent import GuardrailPolicyAgent, ModuleContext
        from opspilot.governance.sentinel_policy.thompson_bandit import ThompsonThresholdBandit

        bandit_path = Path(cfg.get("bandit_state_file", "workspace/sentinel_policy_bandit.json"))
        bandit = ThompsonThresholdBandit.load(bandit_path)
        agent = GuardrailPolicyAgent(bandit=bandit)

        combined_code = "\n".join(state.generated_code.values())
        module_context = ModuleContext(module_id=state.analysis_output.get("program_name", "UNKNOWN"))
        decision = agent.evaluate(combined_code, module_context)

        state.sentinel_policy_decision = {
            "overall_decision": decision.overall_decision,
            "categories": [{"category": c.category, "score": c.score, "threshold": c.threshold,
                             "decision": c.decision} for c in decision.category_decisions],
        }
        agent.bandit.save(bandit_path)

        log_path = Path(cfg.get("decision_log_file", "workspace/sentinel_policy_decisions.json"))
        log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
        log.append(state.sentinel_policy_decision)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")

        self.logger.info(f"[SentinelPolicy] soft-risk decision={decision.overall_decision}")
        if cfg.get("enforce") and decision.overall_decision == "REJECT" and state.is_success:
            state.is_success = False
            state.failure_reason = "SentinelPolicy soft-risk layer rejected the generated code."
            state.phase_status["phase4_governance"] = "VIOLATION"

    def _repo_mind_record_and_propagate(self, state: "PipelineState") -> None:
        """After a module passes Verification+Governance, records it into
        RepoMind's persistent memory and reports which other repo modules a
        change here would propagate to (Idea 4)."""
        cfg = self.extensions_config.get("repo_mind", {})
        if not cfg.get("enabled") or not state.is_success:
            return
        from opspilot.memory.change_propagation_agent import ChangePropagationAgent
        from opspilot.memory.memory_writer import MemoryWriter
        from opspilot.memory.repo_dependency_graph import RepoDependencyGraph
        from opspilot.memory.semantic_memory import SemanticMemory

        graph_path = Path(cfg.get("dependency_graph_file", "workspace/repo_dependency_graph.json"))
        memory_path = Path(cfg.get("semantic_memory_file", "workspace/semantic_memory.json"))
        repo_graph = RepoDependencyGraph.load(graph_path) or RepoDependencyGraph()
        semantic_memory = SemanticMemory.load(memory_path) or SemanticMemory()

        writer = MemoryWriter(repo_graph, semantic_memory)
        program_name = state.analysis_output.get("program_name", "UNKNOWN")
        writer.record_verified_module(
            module_id=program_name,
            rationale=f"Migrated {program_name} ({state.language}) to Java after "
                      f"{state.iteration_count} self-refine iteration(s).",
            edge_cases=[e.get("description", "") for e in state.analysis_output.get("edge_cases", [])] or [],
            tags=[state.language],
        )

        agent = ChangePropagationAgent(repo_graph)
        result = agent.propagate(program_name)
        state.repo_mind_propagation = {
            "changed_node": program_name,
            "scheduled_for_reverification": result.scheduled_for_reverification,
            "scope_fraction": result.scope_fraction,
        }

        repo_graph.save(graph_path)
        semantic_memory.save(memory_path)
        self.logger.info(f"[RepoMind] recorded {program_name}; "
                          f"{len(result.scheduled_for_reverification)} downstream module(s) would need re-verification")

    def run_pipeline(self, source_path: str) -> PipelineResult:
        """Executes the 4-phase OpsPilot modernization flow deterministically."""
        path = Path(source_path)
        state = PipelineState(source_path=str(path))
        self.logger.info(f"Starting OpsPilot Modernization Pipeline for: {path.name}")

        try:
            # -------------------------------------------------------------
            # Phase 1: Deterministic Analysis & AST Extraction (No LLM)
            # -------------------------------------------------------------
            log_phase_transition(self.logger, "Phase 1: Deterministic Analysis", "STARTED")
            state.legacy_source = path.read_text(encoding="utf-8")

            if path.suffix.upper() in [".CBL", ".COB", ".COBOL"]:
                state.language = "COBOL"
                state.analysis_output = parse_cobol_file(path)
            elif path.suffix.upper() in [".SQL", ".PLSQL", ".PLS"]:
                state.language = "PLSQL"
                state.analysis_output = parse_plsql_file(path)
            else:
                # Default fallback parser check
                state.language = "COBOL" if "DIVISION" in state.legacy_source.upper() else "PLSQL"
                state.analysis_output = parse_cobol_file(path) if state.language == "COBOL" else parse_plsql_file(path)

            # Validate against JSON Schema
            is_valid, err_msg = validate_analysis_output(state.analysis_output)
            if not is_valid:
                raise ValueError(f"Phase 1 Output Schema Validation Failed: {err_msg}")

            # Build dependency graph
            dep_builder = DependencyGraphBuilder(state.analysis_output)
            state.dependency_graph = dep_builder.to_dict()
            state.phase_status["phase1_analysis"] = "COMPLETED"
            log_phase_transition(self.logger, "Phase 1: Deterministic Analysis", "COMPLETED", {"program": state.analysis_output.get("program_name")})

            self._repo_mind_ingest_phase1(state)

            # Save Phase 1 analysis output
            out_dir = Path("workspace")
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_dir / "analysis_output.json", "w", encoding="utf-8") as f:
                json.dump(state.analysis_output, f, indent=2)

            # -------------------------------------------------------------
            # Phase 2: Master Orchestration - One-Shot Analysis Agent
            # -------------------------------------------------------------
            log_phase_transition(self.logger, "Phase 2: Master Orchestration", "STARTED")
            analysis_agent = create_analysis_agent(self.config.get("llm", {}))

            # Initiate single-shot chat to extract target OO roadmap
            prompt = f"Analyze this pre-parsed AST summary and provide the Java OO roadmap:\n{json.dumps(state.analysis_output, indent=2)}"
            self.orchestrator_agent.initiate_chat(
                analysis_agent,
                message=prompt,
                max_turns=1
            )

            # Extract Analysis Agent response
            chat_messages = self.orchestrator_agent.chat_messages.get(analysis_agent, [])
            if chat_messages and len(chat_messages) > 0:
                state.design_roadmap = chat_messages[-1].get("content", "Modern Java Spring Boot Microservice Design Roadmap")
            else:
                state.design_roadmap = "Default Spring Boot Service Architecture Roadmap"

            state.phase_status["phase2_orchestration"] = "COMPLETED"
            log_phase_transition(self.logger, "Phase 2: Master Orchestration", "COMPLETED")

            # Save roadmap artifact
            with open(out_dir / "design_roadmap.md", "w", encoding="utf-8") as f:
                f.write(state.design_roadmap)

            # -------------------------------------------------------------
            # Phase 3 & 4: Coder-Verifier Inner Loop with Guardrail Interceptor
            # -------------------------------------------------------------
            log_phase_transition(self.logger, "Phase 3: Autonomous Execution Loop", "STARTED")
            log_phase_transition(self.logger, "Phase 4: Deterministic Guardrails", "ACTIVE")

            coder_agent = create_coder_agent(self.config.get("llm", {}))
            verifier_agent = create_verifier_agent(self.config.get("pipeline", {}).get("sandbox", {}))

            # Register Phase 4 guardrail interceptor on Verifier at position=0
            guardrail_log_file = out_dir / "guardrail_log.json"
            if not guardrail_log_file.exists():
                with open(guardrail_log_file, "w", encoding="utf-8") as f:
                    json.dump([], f, indent=2)

            register_guardrail_interceptor(verifier_agent, guardrail_log_path=guardrail_log_file)

            # Execute bounded self-refine loop
            iteration_budget = self.config.get("pipeline", {}).get("phase3_iteration_budget", 10)
            iteration_budget = self._refine_rl_predict_budget(state, default_budget=iteration_budget)
            loop_result = run_self_refine_loop(
                orchestrator_agent=self.orchestrator_agent,
                coder_agent=coder_agent,
                verifier_agent=verifier_agent,
                design_roadmap=state.design_roadmap,
                analysis_output=state.analysis_output,
                max_turns=iteration_budget
            )

            state.iteration_count = loop_result["turns_used"]
            state.generated_code = loop_result["generated_code"]
            state.verifier_report = loop_result["verifier_report"]

            if loop_result["guardrail_triggered"]:
                state.guardrail_status = "VIOLATION_DETECTED"
                state.phase_status["phase4_governance"] = "VIOLATION"
                state.phase_status["phase3_execution"] = "FAILED"
                state.is_success = False
                state.failure_reason = f"Guardrail Violation: {loop_result['guardrail_reason']}"
                log_phase_transition(self.logger, "Phase 4: Governance", "VIOLATION", {"reason": loop_result['guardrail_reason']})
                if guardrail_log_file.exists():
                    try:
                        with open(guardrail_log_file, "r", encoding="utf-8") as gf:
                            state.guardrail_logs = json.load(gf)
                    except Exception:
                        pass
            elif loop_result["budget_exhausted"]:
                state.phase_status["phase3_execution"] = "BUDGET_EXHAUSTED"
                state.phase_status["phase4_governance"] = "PASSED"
                state.is_success = False
                state.failure_reason = f"Iteration budget ({iteration_budget} turns) exhausted before build success."
                log_phase_transition(self.logger, "Phase 3: Execution Loop", "BUDGET_EXHAUSTED")
            elif loop_result["success"]:
                state.phase_status["phase3_execution"] = "COMPLETED"
                state.phase_status["phase4_governance"] = "PASSED"
                state.is_success = True
                log_phase_transition(self.logger, "Phase 3: Execution Loop", "COMPLETED")

            self._refine_rl_log_outcome(state)
            self._sentinel_policy_evaluate(state)
            self._repo_mind_record_and_propagate(state)

            state.end_time = datetime.now().isoformat()

            # Persist execution artifacts
            with open(out_dir / "verifier_report.json", "w", encoding="utf-8") as f:
                json.dump(state.verifier_report, f, indent=2)

            for filename, code in state.generated_code.items():
                code_file = out_dir / filename
                code_file.parent.mkdir(parents=True, exist_ok=True)
                code_file.write_text(code, encoding="utf-8")

            return PipelineResult(
                success=state.is_success,
                source_path=source_path,
                state=state,
                summary=f"Pipeline completed with status: {state.phase_status}"
            )

        except Exception as ex:
            self.logger.error(f"Pipeline Execution Failed: {str(ex)}", exc_info=True)
            state.end_time = datetime.now().isoformat()
            state.is_success = False
            state.failure_reason = str(ex)
            return PipelineResult(
                success=False,
                source_path=source_path,
                state=state,
                summary=f"Pipeline failed: {str(ex)}"
            )


def run_pipeline(source_path: str, config_path: Optional[Path] = None) -> PipelineResult:
    """Convenience functional entry point for executing the modernization pipeline."""
    orchestrator = MasterOrchestrator(config_path)
    return orchestrator.run_pipeline(source_path)
