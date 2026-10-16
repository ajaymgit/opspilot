"""Pipeline state model tracking modernization state across execution phases."""

from typing import Dict, Any, List, Optional
from datetime import datetime

try:
    from pydantic import BaseModel, Field
except ImportError:
    class _FieldDef:
        def __init__(self, default=None, default_factory=None):
            self.default = default
            self.default_factory = default_factory

        def get_value(self):
            return self.default_factory() if self.default_factory is not None else self.default

    def Field(default=None, default_factory=None):
        return _FieldDef(default=default, default_factory=default_factory)

    class BaseModel:
        def __init__(self, **kwargs):
            # Populate defaults from class attributes
            for k, v in self.__class__.__dict__.items():
                if isinstance(v, _FieldDef):
                    setattr(self, k, v.get_value())
                elif not k.startswith("_") and not callable(v):
                    setattr(self, k, v)
            # Override with explicit keyword arguments
            for k, v in kwargs.items():
                setattr(self, k, v)

        def dict(self, *args, **kwargs) -> Dict[str, Any]:
            return {
                k: getattr(self, k)
                for k in self.__dict__
                if not k.startswith("_") and not callable(getattr(self, k))
            }


class PipelineState(BaseModel):
    """Carries typed pipeline state across Phase 1 -> Phase 2 -> Phase 3 -> Phase 4."""

    source_path: str = ""
    legacy_source: str = ""
    language: str = "UNKNOWN"
    analysis_output: Dict[str, Any] = Field(default_factory=dict)
    dependency_graph: Dict[str, Any] = Field(default_factory=dict)
    design_roadmap: str = ""
    generated_code: Dict[str, str] = Field(default_factory=dict)
    verifier_report: Dict[str, Any] = Field(default_factory=dict)
    guardrail_status: str = "PASSED"
    guardrail_logs: List[Dict[str, Any]] = Field(default_factory=list)
    iteration_count: int = 0
    # -- OpsPilot+ extension fields (populated only if the corresponding
    # extension is enabled in config/llm_config.yaml; otherwise left at their
    # defaults, so base-pipeline behavior and output shape are unchanged) --
    refine_rl_predicted_budget: Optional[int] = None
    sentinel_policy_decision: Dict[str, Any] = Field(default_factory=dict)
    repo_mind_propagation: Dict[str, Any] = Field(default_factory=dict)
    phase_status: Dict[str, str] = Field(
        default_factory=lambda: {
            "phase1_analysis": "PENDING",
            "phase2_orchestration": "PENDING",
            "phase3_execution": "PENDING",
            "phase4_governance": "PENDING"
        }
    )
    start_time: str = Field(default_factory=lambda: datetime.now().isoformat())
    end_time: Optional[str] = None
    is_success: bool = False
    failure_reason: Optional[str] = None


class PipelineResult(BaseModel):
    """Final result container for caller."""

    success: bool = False
    source_path: str = ""
    state: PipelineState = Field(default_factory=PipelineState)
    summary: str = ""
