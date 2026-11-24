"""List G-code command names BlocksScreen emits via *gcode*.emit(...) literals (static AST scan, tab-separated)."""

import ast
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

HOLE = "\x00"  # stands in for any runtime value inside an f-string or concatenation
CMD = re.compile(r"^\s*([A-Z][A-Z0-9_]*)(\x00)?")


@dataclass
class Scan:
    """Commands by name (NAME_* for a dynamic suffix), sends whose command is runtime-only, unparsable files."""

    found: dict[str, set[str]] = field(default_factory=dict)
    dynamic: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


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


def scan(root: Path) -> Scan:
    """Scan every non-resource .py under root for gcode emit calls."""
    result = Scan()
    for path in sorted(root.rglob("*.py")):
        if path.name.endswith("_rc.py"):
            continue
        site = path.relative_to(root)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)  # scanned code's own escape warnings
                tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            result.errors.append(f"{site}: {type(exc).__name__}: {exc}")
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "emit" or "gcode" not in ast.unparse(node.func.value).lower():
                continue
            texts = render(node.args[0]) if node.args else []
            lines = [ln for ln in "\n".join(texts).splitlines() if ln.strip()]
            if node.args and (not texts or any(ln.lstrip().startswith(HOLE) for ln in lines)):
                # Command name built at runtime (variable, call, %, .format): only contract_extra.txt covers it.
                result.dynamic.append(f"{site}:{node.lineno}  {ast.unparse(node.args[0]) if node.args else ''}")
            for line in lines:
                m = CMD.match(line)
                if m:
                    name = m.group(1) + ("*" if m.group(2) else "")
                    result.found.setdefault(name, set()).add(f"{site}:{node.lineno}")
    return result


if __name__ == "__main__":
    res = scan(Path(sys.argv[1]))
    for cmd, sites in sorted(res.found.items()):
        sys.stdout.write(f"{cmd}\t{min(sites)}\t({len(sites)})\n")
    for d in res.dynamic:
        sys.stdout.write(f"DYNAMIC\t{d}\n")
    for e in res.errors:
        sys.stdout.write(f"ERROR\t{e}\n")
