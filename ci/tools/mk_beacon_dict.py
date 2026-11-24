"""Build a synthetic Beacon dict: a Klipper STM32 dict plus beacon_* messages and the live constants."""

import json
import sys
from pathlib import Path

# Message formats beacon.py looks up (BlocksTechnology klipper fork, klippy/extras/beacon.py).
COMMANDS = [
    "beacon_stream en=%u",
    "beacon_set_threshold trigger=%u untrigger=%u",
    "beacon_home trsync_oid=%c trigger_reason=%c trigger_invert=%c",
    "beacon_stop_home",
    "beacon_nvm_read len=%c offset=%hu",
    "beacon_contact_home trsync_oid=%c trigger_reason=%c trigger_type=%c",
    "beacon_contact_query",
    "beacon_contact_stop_home",
    "beacon_contact_set_latency_min latency_min=%c",
    "beacon_contact_set_sensitivity sensitivity=%c",
]
RESPONSES = [
    "beacon_data samples=%c start_clock=%u delta_clock=%u data=%*s",
    "beacon_nvm_data bytes=%*s offset=%hu",
    "beacon_contact_state triggered=%c detect_clock=%u",
    "beacon_status mcu_temp=%u supply_voltage=%u coil_temp=%u status=%u",
    "beacon_contact armed_clock=%u trigger_clock=%u detect_clock=%u latency=%c error=%c",
]
# Only present when BEACON_HAS_ACCEL=1 (RevH on .160). Scale ids are a guess until a captured dict replaces this.
ACCEL_COMMANDS = ["beacon_accel_stream en=%c scale=%c"]
ACCEL_RESPONSES = [
    "beacon_accel_data start_clock=%u delta_clock=%u data=%*s",
    "beacon_accel_state en=%c err=%c",
]
ACCEL_SCALES = {"2g": 0, "4g": 1, "8g": 2, "16g": 3}


def main(base_path: str, fidelity_path: str, out_path: str) -> None:
    """Write out_path from base_path plus the 'mcu beacon' entry of fidelity_path."""
    base = json.loads(Path(base_path).read_text())
    live = json.loads(Path(fidelity_path).read_text())["mcus"]["mcu beacon"]
    used = {v for s in ("commands", "responses", "output") for v in base.get(s, {}).values()}
    next_id = max(used) + 1
    commands, responses = list(COMMANDS), list(RESPONSES)
    if live["mcu_constants"].get("BEACON_HAS_ACCEL"):
        commands += ACCEL_COMMANDS
        responses += ACCEL_RESPONSES
        base.setdefault("enumerations", {})["beacon_accel_scales"] = ACCEL_SCALES
    for sect, msgs in (("commands", commands), ("responses", responses)):
        for msg in msgs:
            base[sect][msg] = next_id
            next_id += 1
    base["config"].update(live["mcu_constants"])
    base["version"] = live["mcu_version"]
    base["app"] = "Beacon"
    Path(out_path).write_text(json.dumps(base))
    sys.stdout.write(f"wrote {out_path} ({live['mcu_version']}, max id {next_id - 1})\n")


if __name__ == "__main__":
    main(*sys.argv[1:4])
