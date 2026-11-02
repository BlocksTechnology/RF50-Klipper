"""Report how far the CI dicts drift from the live RF50 MCUs (warnings only, never fails the run)."""

import json
import sys
from pathlib import Path

# Constants that only differ because CI dicts come from Klipper's generic test configs, not real firmware.
EXPECTED_DRIFT = {"RESERVE_PINS_CAN", "RESERVE_PINS_USB", "CANBUS_FREQUENCY", "SERIAL_BAUD"}


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
        same = "same" if got.get("version") == want["mcu_version"] else "DIFF"
        sys.stdout.write(
            f"  {name:9} version {same} (ci {got.get('version')} / live {want['mcu_version']}), "
            f"msgs {len(got.get('commands', {})) + len(got.get('responses', {}))}, "
            f"{len(diff)} constant diffs\n"
        )
        for k in diff:
            sys.stdout.write(f"      {k}: ci={cfg.get(k)!r} live={live_cfg.get(k)!r}\n")


if __name__ == "__main__":
    main(*sys.argv[1:3])
