"""Canonical denylist rule database for OpsPilot deterministic guardrails.

All governance safety rules are defined as version-controlled data specifications
(string patterns, regexes, and forbidden keywords).
"""

from typing import List, Dict, Any

PROHIBITED_PATTERNS: List[Dict[str, Any]] = [
    {
        "id": "RULE_SYSTEM_EXIT",
        "category": "PROCESS_TERMINATION",
        "pattern": "System.exit",
        "description": "Prohibited explicit JVM system termination call."
    },
    {
        "id": "RULE_RUNTIME_EXEC",
        "category": "COMMAND_INJECTION",
        "pattern": "Runtime.getRuntime().exec",
        "description": "Prohibited arbitrary OS command execution via Runtime."
    },
    {
        "id": "RULE_PROCESS_BUILDER",
        "category": "COMMAND_INJECTION",
        "pattern": "ProcessBuilder",
        "description": "Prohibited OS process builder invocation."
    },
    {
        "id": "RULE_SQL_DROP",
        "category": "DESTRUCTIVE_DDL",
        "pattern": "DROP TABLE",
        "description": "Prohibited destructive DDL DROP TABLE statement."
    },
    {
        "id": "RULE_UNLINK_ALL",
        "category": "FILE_DESTRUCTION",
        "pattern": "rm -rf",
        "description": "Prohibited destructive recursive shell removal."
    },
    {
        "id": "RULE_RAW_JDBC_CONCAT",
        "category": "SQL_INJECTION",
        "pattern": r"(?:SELECT\s+.*?\s+FROM|INSERT\s+INTO|UPDATE\s+.*?SET|DELETE\s+FROM)\s+.*?\+\s*[A-Za-z0-9_]+",
        "is_regex": True,
        "description": "Prohibited un-parameterized raw SQL string concatenation across SELECT, INSERT, UPDATE, or DELETE."
    },
    {
        "id": "RULE_HARDCODED_PASSWORD",
        "category": "SECRET_LEAK",
        "pattern": r"(?:password|passwd|secret_key|api_key)\s*=\s*[\"'][^\"']{4,}[\"']",
        "is_regex": True,
        "description": "Prohibited hardcoded credentials or API secret string."
    }
]


def get_all_prohibited_rules() -> List[Dict[str, Any]]:
    """Returns the canonical list of safety rules."""
    return PROHIBITED_PATTERNS
