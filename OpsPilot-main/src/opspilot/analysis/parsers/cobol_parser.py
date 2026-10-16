"""Deterministic static analysis parser for COBOL legacy source code.

Extracts program boundaries, PERFORM call chains (including THRU, UNTIL, VARYING),
COPYBOOK includes, DATA DIVISION layout (PIC, REDEFINES, OCCURS), embedded SQL
blocks (EXEC SQL ... END-EXEC), and external calls (CALL, CICS).
"""

import re
from pathlib import Path
from typing import Dict, Any, List


class CobolParser:
    """Deterministic AST parser for COBOL code."""

    def __init__(self, source_code: str, source_file: str = "PAYROLL.CBL"):
        self.source_code = source_code
        self.source_file = source_file

    def parse(self) -> Dict[str, Any]:
        """Performs static extraction on the COBOL source and returns structured analysis."""
        lines = self.source_code.splitlines()

        program_name = self._extract_program_name(lines)
        sections = self._extract_sections_and_paragraphs(lines)
        call_graph = self._extract_perform_chains(lines, sections)
        data_structures = self._extract_data_division(lines)
        copybooks = self._extract_copybooks(lines)
        embedded_sql = self._extract_embedded_sql(lines)
        external_calls = self._extract_external_calls(lines)

        return {
            "source_file": self.source_file,
            "language": "COBOL",
            "program_name": program_name,
            "sections_or_procedures": sections,
            "call_graph": call_graph,
            "data_structures": data_structures,
            "copybooks_or_includes": copybooks,
            "embedded_sql": embedded_sql,
            "external_calls": external_calls
        }

    def _extract_program_name(self, lines: List[str]) -> str:
        for line in lines:
            match = re.search(r"PROGRAM-ID\.\s*([\w\-]+)", line, re.IGNORECASE)
            if match:
                return match.group(1).upper()
        return "UNKNOWN_COBOL_PROGRAM"

    def _extract_sections_and_paragraphs(self, lines: List[str]) -> List[Dict[str, Any]]:
        sections = []
        current_name = None
        current_lines = []
        in_procedure = False

        for idx, line in enumerate(lines, start=1):
            clean = line.strip()
            if "PROCEDURE DIVISION" in clean.upper():
                in_procedure = True
                continue
            if not in_procedure or not clean or clean.startswith("*"):
                continue

            # Detect paragraph label e.g., 1000-MAIN-LOGIC. or 2000-EXIT.
            label_match = re.match(r"^([0-9A-Z\-]+)\.\s*$", clean, re.IGNORECASE)
            if label_match:
                if current_name:
                    sections.append({
                        "name": current_name,
                        "type": "PARAGRAPH",
                        "calls": self._find_calls_in_lines(current_lines),
                        "lines": [current_lines[0][0], current_lines[-1][0]] if current_lines else [idx, idx]
                    })
                current_name = label_match.group(1).upper()
                current_lines = [(idx, clean)]
            elif current_name:
                current_lines.append((idx, clean))

        if current_name:
            sections.append({
                "name": current_name,
                "type": "PARAGRAPH",
                "calls": self._find_calls_in_lines(current_lines),
                "lines": [current_lines[0][0], current_lines[-1][0]] if current_lines else [1, 1]
            })

        return sections

    def _find_calls_in_lines(self, line_tuples: List[tuple]) -> List[str]:
        calls = []
        for _, text in line_tuples:
            matches = re.findall(r"PERFORM\s+([0-9A-Z\-]+)", text, re.IGNORECASE)
            for m in matches:
                if m.upper() not in ["VARYING", "UNTIL", "WITH", "TEST"]:
                    calls.append(m.upper())
        return list(dict.fromkeys(calls))

    def _extract_perform_chains(self, lines: List[str], sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        nodes = [s["name"] for s in sections]
        edges = []

        full_text = "\n".join(lines)
        # Match PERFORM target THRU target or PERFORM target UNTIL / VARYING
        perform_pattern = re.compile(
            r"PERFORM\s+([0-9A-Z\-]+)(?:\s+THRU\s+([0-9A-Z\-]+))?(?:\s+UNTIL|\s+VARYING)?",
            re.IGNORECASE
        )

        for sec in sections:
            sec_name = sec["name"]
            for target in sec["calls"]:
                edges.append({
                    "caller": sec_name,
                    "callee": target,
                    "type": "PERFORM"
                })

            # Check THRU targets
            for match in perform_pattern.finditer(full_text):
                caller = sec_name
                start_p = match.group(1).upper()
                thru_p = match.group(2).upper() if match.group(2) else None
                if thru_p and start_p == sec_name:
                    edges.append({
                        "caller": caller,
                        "callee": thru_p,
                        "type": "PERFORM_THRU"
                    })

        return {
            "nodes": nodes,
            "edges": edges
        }

    def _extract_data_division(self, lines: List[str]) -> List[Dict[str, Any]]:
        data_items = []
        in_data = False

        for line in lines:
            clean = line.strip()
            if "DATA DIVISION" in clean.upper():
                in_data = True
                continue
            if "PROCEDURE DIVISION" in clean.upper():
                in_data = False
                break
            if not in_data or not clean or clean.startswith("*"):
                continue

            # Level number and field name
            match = re.match(r"^(\d{2})\s+([0-9A-Z\-]+)(.*)", clean, re.IGNORECASE)
            if match:
                level = match.group(1)
                name = match.group(2).upper()
                rest = match.group(3).upper()

                pic_match = re.search(r"PIC\s+([X9V\(\)\.\-]+)", rest)
                redef_match = re.search(r"REDEFINES\s+([0-9A-Z\-]+)", rest)
                occurs_match = re.search(r"OCCURS\s+(\d+)\s+TIMES", rest)

                item = {
                    "name": name,
                    "level_or_type": f"LEVEL_{level}",
                    "pic": pic_match.group(1) if pic_match else "",
                    "redefines": redef_match.group(1) if redef_match else "",
                    "occurs": int(occurs_match.group(1)) if occurs_match else 0
                }
                data_items.append(item)

        return data_items

    def _extract_copybooks(self, lines: List[str]) -> List[str]:
        copybooks = []
        for line in lines:
            match = re.search(r"COPY\s+[\"']?([0-9A-Z\.\-]+)[\"']?", line, re.IGNORECASE)
            if match:
                copybooks.append(match.group(1).upper().replace('"', '').replace("'", ''))
        return list(dict.fromkeys(copybooks))

    def _extract_embedded_sql(self, lines: List[str]) -> List[Dict[str, Any]]:
        sql_blocks = []
        full_text = "\n".join(lines)

        sql_matches = re.finditer(r"EXEC\s+SQL\s+(.*?)\s+END-EXEC", full_text, re.DOTALL | re.IGNORECASE)
        for match in sql_matches:
            raw_sql = match.group(1).strip()
            # Determine statement type (SELECT, UPDATE, INSERT, DELETE, INCLUDE)
            sql_upper = raw_sql.upper()
            st_type = "UNKNOWN"
            if "SELECT" in sql_upper:
                st_type = "SELECT"
            elif "UPDATE" in sql_upper:
                st_type = "UPDATE"
            elif "INSERT" in sql_upper:
                st_type = "INSERT"
            elif "DELETE" in sql_upper:
                st_type = "DELETE"
            elif "INCLUDE" in sql_upper:
                st_type = "INCLUDE"

            # Extract table references e.g. FROM TAX_RATES or INTO TAX_RATES
            tables = re.findall(r"(?:FROM|INTO|UPDATE)\s+([A-Z0-9_\.]+)", sql_upper)

            sql_blocks.append({
                "statement_type": st_type,
                "tables": list(dict.fromkeys(tables)),
                "columns": [],
                "raw_sql": raw_sql
            })

        return sql_blocks

    def _extract_external_calls(self, lines: List[str]) -> List[Dict[str, Any]]:
        calls = []
        for line in lines:
            clean = line.strip()
            # COBOL CALL 'PROGRAM' USING ...
            call_match = re.search(r"CALL\s+[\"']([0-9A-Z\-]+)[\"'](?:\s+USING\s+(.*))?", clean, re.IGNORECASE)
            if call_match:
                prog = call_match.group(1).upper()
                params_str = call_match.group(2) or ""
                params = [p.strip() for p in re.split(r"[\s,]+", params_str) if p.strip()]
                calls.append({
                    "target": prog,
                    "call_type": "CALL",
                    "parameters": params
                })
            # CICS calls e.g., EXEC CICS ...
            elif "EXEC CICS" in clean.upper():
                calls.append({
                    "target": "CICS_EXEC",
                    "call_type": "EXEC_CICS",
                    "parameters": [clean]
                })

        return calls


def parse_cobol_file(file_path: Path) -> Dict[str, Any]:
    """Helper to parse a COBOL file from disk."""
    code = file_path.read_text(encoding="utf-8")
    parser = CobolParser(source_code=code, source_file=file_path.name)
    return parser.parse()
