"""Flatten OrcaSlicer system presets so the Orca CLI can slice the CI print fixture.

Usage: orca_flatten.py <profiles/Blocks> <machine name> <process name> <filament name> <outdir>
Writes machine.json, process.json, filament.json; recipe in ci/README.md ("Print fixture").
"""

import json
import sys
from pathlib import Path


def index(d: Path) -> dict[str, Path]:
    """Map preset name to file for one profile subdirectory."""
    return {json.loads(p.read_text()).get("name", p.stem): p for p in d.glob("*.json")}


def resolve(name: str, idx: dict[str, Path]) -> dict:
    """Merge a preset over its 'inherits' chain, child keys winning (the CLI does not resolve it)."""
    d = json.loads(idx[name].read_text())
    parent = d.pop("inherits", None)
    base = resolve(parent, idx) if parent else {}
    base.update(d)
    return base


def main(argv: list[str]) -> int:
    """Write the three flattened presets."""
    if len(argv) != 6:
        sys.stderr.write(__doc__ or "")
        return 2
    root, machine, process, filament, out = Path(argv[1]), argv[2], argv[3], argv[4], Path(argv[5])
    out.mkdir(parents=True, exist_ok=True)
    m = resolve(machine, index(root / "machine"))
    # Orca 2.4 checks compatible_printers against the printer's system name, empty for a "User" preset (-17).
    m["from"] = "system"
    for kind, name in (("process", process), ("filament", filament)):
        d = resolve(name, index(root / kind))
        d.pop("compatible_printers_condition", None)
        d["compatible_printers"] = [machine]
        d["from"] = "User"
        (out / f"{kind}.json").write_text(json.dumps(d, indent=1))
    (out / "machine.json").write_text(json.dumps(m, indent=1))
    sys.stdout.write(f"orca_flatten: presets in {out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
