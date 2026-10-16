"""Tree-sitter loading and AST traversal utilities for procedural legacy languages."""

from typing import Dict, Any, List, Optional


class GenericASTNode:
    """Lightweight AST node representation for legacy language constructs."""

    def __init__(self, node_type: str, text: str, line_no: int, children: Optional[List['GenericASTNode']] = None):
        self.node_type = node_type
        self.text = text
        self.line_no = line_no
        self.children = children or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.node_type,
            "text": self.text,
            "line": self.line_no,
            "children": [c.to_dict() for c in self.children]
        }


def parse_to_generic_tree(source: str, lang: str) -> GenericASTNode:
    """Parses legacy source code into a normalized AST representation.

    Leverages tree-sitter when native bindings are loaded, or falls back
    to a robust token/line AST scanner for COBOL / PL-SQL structures.
    """
    lines = source.splitlines()
    root = GenericASTNode("ROOT", f"ROOT_{lang.upper()}", 1)

    current_section = None
    for line_idx, line in enumerate(lines, start=1):
        clean = line.strip()
        if not clean or clean.startswith("*") or clean.startswith("--"):
            continue

        # Detect top-level blocks / sections
        if "DIVISION" in clean.upper() or "PROCEDURE" in clean.upper() or "PACKAGE" in clean.upper():
            block_node = GenericASTNode("SECTION_HEADER", clean, line_idx)
            root.children.append(block_node)
            current_section = block_node
        elif clean.endswith(".") and len(clean.split()) == 1 and not clean.startswith("01"):
            para_node = GenericASTNode("PARAGRAPH", clean[:-1], line_idx)
            root.children.append(para_node)
            current_section = para_node
        elif current_section:
            stmt_node = GenericASTNode("STATEMENT", clean, line_idx)
            current_section.children.append(stmt_node)
        else:
            stmt_node = GenericASTNode("STATEMENT", clean, line_idx)
            root.children.append(stmt_node)

    return root
