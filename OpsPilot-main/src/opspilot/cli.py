"""CLI entrypoint for OpsPilot legacy-code modernization commands."""

import argparse
import json
import sys
from pathlib import Path

from opspilot.orchestration.master_orchestrator import run_pipeline
from opspilot.analysis.parsers.cobol_parser import parse_cobol_file
from opspilot.analysis.parsers.plsql_parser import parse_plsql_file
from opspilot.utils.json_schema import validate_analysis_output


def analyze_command(file_path: str):
    """Executes Phase 1 static AST parsing and prints summary."""
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File '{file_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Running Phase 1 Static Analysis on: {path.name}")
    if path.suffix.upper() in [".CBL", ".COB", ".COBOL"]:
        analysis = parse_cobol_file(path)
    elif path.suffix.upper() in [".SQL", ".PLSQL", ".PLS"]:
        analysis = parse_plsql_file(path)
    else:
        # Infer language
        text = path.read_text(encoding="utf-8")
        analysis = parse_cobol_file(path) if "DIVISION" in text.upper() else parse_plsql_file(path)

    is_valid, err_msg = validate_analysis_output(analysis)
    if not is_valid:
        print(f"[!] Schema Validation Error: {err_msg}", file=sys.stderr)
        sys.exit(1)

    print(f"[+] Analysis Completed Successfully. Program: {analysis.get('program_name')}")
    print(json.dumps(analysis, indent=2))


def pipeline_command(file_path: str):
    """Executes full modernization pipeline."""
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File '{file_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Launching OpsPilot Modernization Pipeline for: {path.name}")
    result = run_pipeline(str(path))

    if result.success:
        print("\n[SUCCESS] PIPELINE COMPLETED SUCCESSFULLY!")
        print(f"Source: {result.source_path}")
        print(f"Turns Used: {result.state.iteration_count}")
        print(f"Generated Files: {list(result.state.generated_code.keys())}")
    else:
        print("\n[FAILED] PIPELINE EXECUTION FAILED!")
        print(f"Reason: {result.state.failure_reason}")
        print(f"Status: {result.state.phase_status}")
        sys.exit(1)


def evaluate_extensions_command(which: str, output_dir: str):
    """Runs the OpsPilot+ research-extension evaluation harnesses and prints
    their summaries. `which` is one of: sentinel_policy, refine_rl, repo_mind, all."""
    out = Path(output_dir)

    def _run_sentinel_policy():
        from opspilot.governance.sentinel_policy.evaluate import run_evaluation
        summary, *_ = run_evaluation(output_dir=out / "sentinel_policy")
        print("\n=== SentinelPolicy (adaptive guardrail thresholds) ===")
        print(json.dumps(summary, indent=2))

    def _run_refine_rl():
        from opspilot.execution.refine_rl.evaluate import run_evaluation, run_budget_sweep
        summary, *_ = run_evaluation(output_dir=out / "refine_rl")
        print("\n=== RefineRL (predictive iteration budget) ===")
        print(json.dumps(summary, indent=2))
        frontier, rl_summary = run_budget_sweep(output_dir=out / "refine_rl")
        print(json.dumps({"fixed_budget_frontier": frontier, "refine_rl": rl_summary}, indent=2))

    def _run_repo_mind():
        from opspilot.memory.evaluate_propagation import run_evaluation as prop_eval
        from opspilot.memory.evaluate_semantic_recall import run_evaluation as recall_eval
        summary, _ = prop_eval(output_dir=out / "repo_mind")
        print("\n=== RepoMind: change propagation ===")
        print(json.dumps(summary, indent=2))
        recall_summary = recall_eval(output_dir=out / "repo_mind")
        print("\n=== RepoMind: semantic memory recall ===")
        print(json.dumps(recall_summary, indent=2))

    runners = {"sentinel_policy": _run_sentinel_policy, "refine_rl": _run_refine_rl, "repo_mind": _run_repo_mind}
    if which == "all":
        for r in runners.values():
            r()
    else:
        runners[which]()


def audit_command(output_json=None):
    """Executes comprehensive system audits and prints report."""
    from opspilot.audit.auditor import OpsPilotAuditor
    auditor = OpsPilotAuditor()
    report = auditor.run_all_audits()
    print(report.summary_text())

    if output_json:
        out_path = Path(output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)
        print(f"\n[+] Detailed audit JSON exported to: {out_path}")

    if report.has_faults:
        sys.exit(1)


def serve_command(host: str = "127.0.0.1", port: int = 8080):
    """Launches the OpsPilot drag-and-drop web modernization interface."""
    from opspilot.ui.server import start_server
    start_server(host=host, port=port)


def main():
    parser = argparse.ArgumentParser(description="OpsPilot Legacy-Code Modernization System")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="Run Phase 1 static analysis on legacy source file")
    analyze_parser.add_argument("file", help="Path to legacy file (.CBL, .SQL)")

    pipeline_parser = subparsers.add_parser("run-pipeline", help="Run complete OpsPilot modernization pipeline")
    pipeline_parser.add_argument("file", help="Path to legacy file (.CBL, .SQL)")

    eval_parser = subparsers.add_parser("evaluate-extensions",
                                         help="Run OpsPilot+ research-extension evaluation harnesses")
    eval_parser.add_argument("which", choices=["sentinel_policy", "refine_rl", "repo_mind", "all"], default="all",
                              nargs="?")
    eval_parser.add_argument("--output-dir", default="workspace/extension_eval")

    audit_parser = subparsers.add_parser("audit", help="Run comprehensive architectural, security, and static code audits")
    audit_parser.add_argument("--json", dest="output_json", help="Path to export audit JSON report")

    serve_parser = subparsers.add_parser("serve", help="Launch interactive drag-and-drop modernization web UI")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")

    args = parser.parse_args()

    if args.command == "analyze":
        analyze_command(args.file)
    elif args.command == "run-pipeline":
        pipeline_command(args.file)
    elif args.command == "evaluate-extensions":
        evaluate_extensions_command(args.which, args.output_dir)
    elif args.command == "audit":
        audit_command(args.output_json)
    elif args.command == "serve":
        serve_command(args.host, args.port)


if __name__ == "__main__":
    main()
