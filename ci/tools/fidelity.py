"""Report how far the CI dicts drift from the live RF50 MCUs (warnings only, never fails the run)."""

import json
import re
import sys
from pathlib import Path

# Constants that only differ because CI dicts come from Klipper's generic test configs, not real firmware.
EXPECTED_DRIFT = {"RESERVE_PINS_CAN", "RESERVE_PINS_USB", "CANBUS_FREQUENCY", "SERIAL_BAUD"}
# Klipper's build appends -<date>_<time>-<host>; live mcu_version has it stripped.
BUILD_SUFFIX = re.compile(r"-\d{8}_\d{6}-\S+$")
# A build without tags reports a bare short hash; one with tags reports git describe (...-g<hash>).
DESCRIBE_HASH = re.compile(r"(?:^|-g)([0-9a-f]{7,40})$")


def same_build(ci: str, live: str) -> bool:
    """True when both version strings name the same commit, whatever their describe format."""
    ci = BUILD_SUFFIX.sub("", ci)
    a, b = DESCRIBE_HASH.search(ci), DESCRIBE_HASH.search(live)
    if a and b:
        return a[1].startswith(b[1]) or b[1].startswith(a[1])
    return ci == live


def klippy_count(d: dict) -> int:
    """Message count as klippy.log 'Loaded MCU ... N commands' prints it: msgproto adds 2 identify messages."""
    return sum(len(d.get(s, {})) for s in ("commands", "responses", "output")) + 2


def main(dict_dir: str, fidelity_path: str) -> None:
    """Compare version and constants of dict_dir/<name>.dict against the 'mcu <name>' entries."""
    live = json.loads(Path(fidelity_path).read_text())
    sys.stdout.write(f"fidelity vs {live['source']}\n")
    for key, want in live["mcus"].items():
        name = "mcu" if key == "mcu" else key.split(" ", 1)[1]
        path = Path(dict_dir) / f"{name}.dict"
        if not path.exists():
            sys.stdout.write(f"  {name:9} no CI dict (not booted in this variant)\n")
            continue
        got = json.loads(path.read_text())
        cfg, live_cfg = got.get("config", {}), want["mcu_constants"]
        # Live keys only: generic test-config builds add bus/pin constants the real firmware never had.
        diff = sorted(
            k for k in live_cfg if str(cfg.get(k)) != str(live_cfg[k]) and k not in EXPECTED_DRIFT
        )
        same = "same" if same_build(str(got.get("version")), want["mcu_version"]) else "DIFF"
        sys.stdout.write(
            f"  {name:9} version {same} (ci {got.get('version')} / live {want['mcu_version']}), "
            f"msgs {klippy_count(got)}, "
            f"{len(diff)} constant diffs\n"
        )
        for k in diff:
            sys.stdout.write(f"      {k}: ci={cfg.get(k)!r} live={live_cfg.get(k)!r}\n")


if __name__ == "__main__":
    main(*sys.argv[1:3])
