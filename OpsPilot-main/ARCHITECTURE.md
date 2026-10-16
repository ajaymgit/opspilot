# OpsPilot System Architecture

OpsPilot is a legacy-code modernization system that transforms legacy procedural source code (COBOL, PL-SQL) into modern Java Spring Boot microservices. It is built on a **Hybrid Nested-Orchestration Architecture** combining deterministic Python control flow with bounded, isolated multi-agent sub-chats built on AutoGen.

---

## 4 Non-Negotiable Design Constraints Checklist

Every contributor and automated test suite must enforce these four non-negotiable architectural rules:

- [x] **Constraint 1: Deterministic Static Analysis**
  *Never feed raw legacy source directly into an LLM and ask it to "parse the AST."* All structural parsing, program/section boundaries, PERFORM chains, COPYBOOK includes, PIC clauses, REDEFINES, OCCURS arrays, embedded SQL, and CURSOR loops must be extracted by deterministic static analysis tooling in Python (`tree-sitter`, regex, AST parsers). The LLM receives only pre-parsed, JSON Schema-validated summaries.

- [x] **Constraint 2: No Flat GroupChat**
  *Never put all agents into a single flat GroupChat.* Group chats introduce non-deterministic turn-taking and cross-phase pollution. Master pipeline orchestration is strictly managed by a deterministic Python control plane (`master_orchestrator.py`) using sequential/nested AutoGen `UserProxyAgent` triggers.

- [x] **Constraint 3: Strict Inner Loop Isolation**
  *Never let the Analysis Agent or Guardrail Agent participate in the inner Coder-Verifier execution loop.* The self-refinement loop is strictly restricted to exactly two agents: `Coder` (`AssistantAgent`) and `Verifier` (`UserProxyAgent`), bounded by a hardcoded turn iteration budget ($B=10$). Budget exhaustion triggers explicit pipeline failure.

- [x] **Constraint 4: Deterministic Python Safety Guardrails**
  *Never rely on an LLM "SafeguardAgent" that evaluates code safety via prompting.* All safety, governance, and security checks are hardcoded Python validation functions (regex, string patterns, AST rules) registered as interceptors at `position=0` via AutoGen's `register_reply` mechanism on the Verifier agent. Interceptors run before any code execution side effect occurs.

---

## High-Level Architecture Diagram

```
[Legacy Source Code (COBOL / PL-SQL)]
        │
        ▼
┌────────────────────────────────────────────────────────┐
│   Phase 1: Deterministic Analysis & AST Extraction      │  (Python Parsers / Tree-Sitter / NetworkX)
│   - cobol_parser.py, plsql_parser.py                   │
│   - Emits schema-validated analysis_output.json        │
└───────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────┐
│       Phase 2: Master Orchestrator Pipeline             │  (Sequential / Nested AutoGen Orchestration)
│   - Python Control Plane (pipeline_state.py)            │
│   - Triggers one-shot AnalysisAgent for OO Roadmap     │
└───────┬────────────────────────────────────────┬────────┘
        │                                        │
        ▼                                        ▼
┌─────────────────────────────┐   ┌─────────────────────────────┐
│  Phase 3: Coder–Verifier    │   │ Phase 4: Deterministic       │
│  Nested Loop (Self-Refine)  │──▶│ Guardrail Interceptor        │
│  (2-Agent Dedicated Chat)   │   │ (AutoGen register_reply)     │
│  - Bounded iteration budget │   │ - Intercepts at position=0   │
│  - Sandboxed execution      │   │ - Hardcoded Python rules     │
└─────────────────────────────┘   └─────────────────────────────┘
```

---

## Phase Workflow Details

### Phase 1: Deterministic Analysis & AST Extraction
- **Input**: Raw `.CBL` or `.SQL` legacy files.
- **Processing**:
  - `cobol_parser.py`: Parses IDENTIFICATION, ENVIRONMENT, DATA, and PROCEDURE divisions; resolves `COPY` books; builds `PERFORM` call chains (`THRU`, `UNTIL`, `VARYING`); extracts `PIC`, `REDEFINES`, `OCCURS`; extracts `EXEC SQL`.
  - `plsql_parser.py`: Parses package/procedure/function definitions, parameters, table/column references, DML statements, CURSOR loops, and EXCEPTION blocks.
  - `dependency_graph.py`: Constructs a directed graph of calls and dependencies using `networkx`.
- **Output**: Versioned `analysis_output.json` validated against `json_schema.py`.

### Phase 2: Master Orchestration (Control Plane)
- **Engine**: `master_orchestrator.py`
- **State**: Typed `PipelineState` tracking phase status, timestamps, analysis outputs, design roadmaps, generated code, verifier reports, and guardrail audit logs.
- **Flow**:
  1. Executes Phase 1 parser -> `analysis_output`.
  2. Sends `analysis_output` to `AnalysisAgent` in a single-shot chat -> `design_roadmap`.
  3. Passes `design_roadmap` into Phase 3 self-refinement loop.
  4. Applies Phase 4 guardrails on all outgoing messages.
  5. Saves artifacts in `workspace/` and outputs pipeline status report.

### Phase 3: Autonomous Execution & Feedback Loop
- **Participants**: Strictly 2 agents (`Coder` and `Verifier`).
- **Iteration Budget**: Hard-capped at $B=10$ turns (configurable in `config/llm_config.yaml`).
- **Feedback**: Verifier runs tests in `workspace/` sandbox (local/docker). On failure, Verifier returns exact compiler/test log; Coder fixes **only** reported errors to avoid code regression.

### Phase 4: Governance Layer (Deterministic Guardrails)
- **Mechanism**: AutoGen `verifier.register_reply(..., reply_func=deterministic_guardrail_check, position=0)`.
- **Denylist Rules**:
  - Prohibited calls: `System.exit`, `Runtime.getRuntime().exec`, `DROP TABLE`, `rm -rf`.
  - Security violations: Raw JDBC string concatenation, hardcoded API keys/passwords, unauthorized outbound network requests.
- **Audit**: Every violation logs full context to `guardrail_log.json` and immediately halts pipeline execution with `GUARDRAIL_VIOLATION`.

---

## OpsPilot+ Research Extensions

Three optional extensions (`governance/sentinel_policy/`, `execution/refine_rl/`,
`memory/`) implement research directions from the accompanying survey, layered
around -- never inside -- the four phases above. All default to disabled and
have been individually checked against all four non-negotiable constraints
listed at the top of this document; see `docs/IMPLEMENTATION_NOTES.md` Section
3 for the constraint-by-constraint compliance table and the reasoning behind
which of the ten candidate research directions were implemented versus
deliberately excluded (most notably: a fourth candidate, adaptive topology
selection, was excluded specifically *because* it conflicts with Constraint 2
above).
