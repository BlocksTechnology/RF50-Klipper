"""List G-code command names BlocksScreen emits via *gcode*.emit(...) literals (static AST scan, tab-separated)."""

import ast
import re
import sys
import warnings
from pathlib import Path

HOLE = "\x00"  # stands in for any runtime value inside an f-string or concatenation
CMD = re.compile(r"^\s*([A-Z][A-Z0-9_]*)(\x00)?")


def render(node: ast.expr) -> list[str]:
    """Possible texts of a str literal / f-string / concatenation / a-if-c-else-b, HOLE for dynamic parts."""
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    if isinstance(node, ast.JoinedStr):
        return ["".join(str(v.value) if isinstance(v, ast.Constant) else HOLE for v in node.values)]
    if isinstance(node, ast.IfExp):
        return render(node.body) + render(node.orelse)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = render(node.left), render(node.right)
        if not left and not right:
            return []
        return [a + b for a in left or [HOLE] for b in right or [HOLE]]
    return []


def scan(root: Path) -> dict[str, set[str]]:
    """Map command name (NAME_* for a dynamic suffix) to the emit sites that send it."""
    found: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        if path.name.endswith("_rc.py"):
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)  # scanned code's own escape warnings
                tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "emit" or "gcode" not in ast.unparse(node.func.value).lower():
                continue
            texts = render(node.args[0]) if node.args else []
            for line in "\n".join(texts).splitlines():
                m = CMD.match(line)
                if not m:
                    continue  # empty line or a command name only known at runtime
                name = m.group(1) + ("*" if m.group(2) else "")
                found.setdefault(name, set()).add(f"{path.relative_to(root)}:{node.lineno}")
    return found


if __name__ == "__main__":
    for cmd, sites in sorted(scan(Path(sys.argv[1])).items()):
        sys.stdout.write(f"{cmd}\t{sorted(sites)[0]}\t({len(sites)})\n")
