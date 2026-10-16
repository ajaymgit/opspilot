"""JSON Schema definitions and validation utilities for OpsPilot data contracts."""

from typing import Dict, Any, Tuple

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

ANALYSIS_OUTPUT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": [
        "source_file",
        "language",
        "program_name",
        "sections_or_procedures",
        "call_graph",
        "data_structures",
        "copybooks_or_includes",
        "embedded_sql",
        "external_calls"
    ],
    "properties": {
        "source_file": {"type": "string"},
        "language": {"type": "string", "enum": ["COBOL", "PLSQL", "UNKNOWN"]},
        "program_name": {"type": "string"},
        "sections_or_procedures": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "calls": {"type": "array", "items": {"type": "string"}},
                    "lines": {"type": "array", "items": {"type": "integer"}}
                }
            }
        },
        "call_graph": {
            "type": "object",
            "required": ["nodes", "edges"],
            "properties": {
                "nodes": {"type": "array", "items": {"type": "string"}},
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["caller", "callee"],
                        "properties": {
                            "caller": {"type": "string"},
                            "callee": {"type": "string"},
                            "type": {"type": "string"}
                        }
                    }
                }
            }
        },
        "data_structures": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "level_or_type"],
                "properties": {
                    "name": {"type": "string"},
                    "level_or_type": {"type": "string"},
                    "pic": {"type": "string"},
                    "redefines": {"type": "string"},
                    "occurs": {"type": "integer"}
                }
            }
        },
        "copybooks_or_includes": {"type": "array", "items": {"type": "string"}},
        "embedded_sql": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["statement_type", "tables"],
                "properties": {
                    "statement_type": {"type": "string"},
                    "tables": {"type": "array", "items": {"type": "string"}},
                    "columns": {"type": "array", "items": {"type": "string"}},
                    "raw_sql": {"type": "string"}
                }
            }
        },
        "external_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["target", "call_type"],
                "properties": {
                    "target": {"type": "string"},
                    "call_type": {"type": "string"},
                    "parameters": {"type": "array", "items": {"type": "string"}}
                }
            }
        }
    }
}

VERIFIER_REPORT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["status", "build_success", "logs", "timestamp"],
    "properties": {
        "status": {"type": "string", "enum": ["SUCCESS", "FAILED", "GUARDRAIL_VIOLATION"]},
        "build_success": {"type": "boolean"},
        "logs": {"type": "string"},
        "failed_tests": {"type": "array", "items": {"type": "string"}},
        "timestamp": {"type": "string"}
    }
}

GUARDRAIL_LOG_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["timestamp", "matched_rule", "offending_message", "pipeline_stage"],
    "properties": {
        "timestamp": {"type": "string"},
        "matched_rule": {"type": "string"},
        "offending_message": {"type": "string"},
        "pipeline_stage": {"type": "string"}
    }
}


def _fallback_validate(data: Any, schema: Dict[str, Any], path: str = "root") -> Tuple[bool, str]:
    """Lightweight deterministic schema validator when jsonschema library is unavailable."""
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(data, dict):
            return False, f"Expected object at {path}, got {type(data).__name__}"

        for req in schema.get("required", []):
            if req not in data:
                return False, f"Missing required property '{req}' at {path}"

        properties = schema.get("properties", {})
        for key, val in data.items():
            if key in properties:
                ok, err = _fallback_validate(val, properties[key], path=f"{path}.{key}")
                if not ok:
                    return False, err

    elif expected_type == "array":
        if not isinstance(data, list):
            return False, f"Expected array at {path}, got {type(data).__name__}"
        item_schema = schema.get("items")
        if item_schema and isinstance(item_schema, dict):
            for idx, item in enumerate(data):
                ok, err = _fallback_validate(item, item_schema, path=f"{path}[{idx}]")
                if not ok:
                    return False, err

    elif expected_type == "string":
        if not isinstance(data, str):
            return False, f"Expected string at {path}, got {type(data).__name__}"
        if "enum" in schema and data not in schema["enum"]:
            return False, f"Value '{data}' at {path} not in enum {schema['enum']}"

    elif expected_type == "integer":
        if not isinstance(data, int) or isinstance(data, bool):
            return False, f"Expected integer at {path}, got {type(data).__name__}"

    elif expected_type == "boolean":
        if not isinstance(data, bool):
            return False, f"Expected boolean at {path}, got {type(data).__name__}"

    return True, "Valid"


def validate_analysis_output(data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates analysis JSON output against the schema."""
    if HAS_JSONSCHEMA:
        try:
            jsonschema.validate(instance=data, schema=ANALYSIS_OUTPUT_SCHEMA)
            return True, "Valid"
        except jsonschema.ValidationError as err:
            return False, str(err)
    return _fallback_validate(data, ANALYSIS_OUTPUT_SCHEMA)


def validate_verifier_report(data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates verifier report JSON against the schema."""
    if HAS_JSONSCHEMA:
        try:
            jsonschema.validate(instance=data, schema=VERIFIER_REPORT_SCHEMA)
            return True, "Valid"
        except jsonschema.ValidationError as err:
            return False, str(err)
    return _fallback_validate(data, VERIFIER_REPORT_SCHEMA)


def validate_guardrail_log(data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates guardrail log JSON against the schema."""
    if HAS_JSONSCHEMA:
        try:
            jsonschema.validate(instance=data, schema=GUARDRAIL_LOG_SCHEMA)
            return True, "Valid"
        except jsonschema.ValidationError as err:
            return False, str(err)
    return _fallback_validate(data, GUARDRAIL_LOG_SCHEMA)
