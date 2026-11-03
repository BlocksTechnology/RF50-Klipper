# RF50 clone: batch-mode Klipper CI for RF50-Klipper

Boots the real RF50 config on the pinned BlocksTechnology Klipper fork with no hardware, using Klipper's own
batch mode and `scripts/test_klippy.py` (the method Klipper's CI uses). Software pins mirror the stage
machine .160, surveyed 2026-11-02 (`pins.env`, `fidelity-rf50-160.json`). Variant: no-AMU (`variant_sync_single`).

```
./bootstrap.sh     # once per pin: fork trees, venv (py3.11), MCU dicts -> .cache/
./run_tests.sh     # all tests + generated BlocksScreen contract test; exit 1 on any failure
./run_tests.sh tests/stub/home_jog.test
```

Local shortcuts: `KLIPPER_SRC=<fork clone>` skips the clone, `CI_VENV=<venv>` reuses a venv,
`CONFIG_DIR=<cfg dir>` or `CONFIG_REPO`/`CONFIG_REF` pick the config, `BS_DIR` or `BS_REPO`/`BS_REF` the BlocksScreen source.

| Path | What |
|---|---|
| `tests/real/` | runs with the fork's real `beacon.py` (boot, strict-unknown guard, contract) |
| `tests/stub/` | runs with `stubs/beacon.py`; motion needs it (real Beacon waits for samples batch mode never sends): home/jog, sliced print, PAUSE/RESUME/CANCEL, PRINT_START refusing an unloaded machine |
| `klipper_plugins/ci_batch_shims.py` | CI-only extra: unknown command = error, `CI_ASSERT_COMMANDS` (exact names), `CI_SET_FILAMENT PRESENT=0\|1` (all switch sensors), `CI_MMU_PRINT_SYNC ENABLE=0\|1`, batch EOF held until an SD print ends (fails unless it completes), aht10/beacon connect no-ops, absolute `log_file` |
| `gcodes/` | `virtual_sdcard` root for `SDCARD_PRINT_FILE` tests: a real OrcaSlicer RF50 file and its STL (see Print fixture) |
| `tools/orca_flatten.py` | flattens the Blocks Orca presets for the slicer CLI (fixture regeneration only) |
| `contract_skip.txt` | BlocksScreen commands the config may lack, each with a reason; an entry matching nothing fails the run |
| `contract_extra.txt` | names the scan cannot see: sends built at runtime, and `NAME_*=A,B` expansions for suffixed sends |
| `fidelity-rf50-160.json` | live .160 MCU versions and constants; required input (beacon dict synthesis + fidelity report) |
| `tools/fidelity.py` | CI dicts vs live .160 constants, report only |
| `dicts/captured/<mcu>.dict` | .160-exact dicts (copied or rebuilt from the live commits), used instead of the generic builds (see MCU dicts) |

Not covered yet: AMU variant (`MMU_*`, mmu MCU), print core (`CHANGE_PRINTCORES`, WIP).

MCU dicts (2026-11-03): `pi.dict` is .160's own `~/klipper/out/klipper.dict` (its build hash equals the running
`klipper_mcu`). `mcu.dict` (fork 14edee70) and `Toolhead.dict` (upstream 9346ad191) are rebuilt from those commits
with the board options below; message count (137/136, as klippy.log prints it) and every constant match the live
MCUs, and `version`/`build_versions` are set to the live strings. Beacon stays synthesised (closed firmware).
- mcu, Octopus Pro H723: `STM32H723`, 128KiB bootloader, 25 MHz crystal, USB-to-CAN bridge (USB PA11/PA12, CAN PD0/PD1), 1 Mbit
- Toolhead, EBB36 G0B1: `STM32G0B1`, 8KiB bootloader, 8 MHz crystal, CAN PB0/PB1, 1 Mbit

Each `# CI_EXPECT_LOG: text` line in a `.test` makes the runner also require that text in the runtime log (config
dump excluded), so a SHOULD_FAIL test cannot pass for the wrong reason.

Contract: every literal command BlocksScreen emits must be a registered command name (exact match). The run prints
`contract: dynamic` for sends it cannot read; cover each in `contract_extra.txt` or `contract_skip.txt`.
Stale skips/expansions, unparseable sources and an implausibly small scan all fail the run.

Print fixture: `gcodes/rf50_cube_pla.gcode` is a 15x15x1.2 mm cube sliced by OrcaSlicer 2.4.2 with the stock Blocks
presets, so it carries the real start/end G-code (`PRINT_START`, `PRINT_END`). It prints through `virtual_sdcard`,
the path Moonraker uses. Regenerate it after a preset change (the CLI does not resolve `inherits`, hence the flatten):

```
P=/opt/orca-slicer/resources/profiles/Blocks
python3 tools/orca_flatten.py "$P" "BLOCKS RF50 0.4 nozzle" "0.20mm Standard 0.4 nozzle @Blocks_RF50" "Blocks Generic PLA" /tmp/orca
orca-slicer --load-settings "/tmp/orca/machine.json;/tmp/orca/process.json" --load-filaments /tmp/orca/filament.json \
  --arrange 1 --slice 0 --outputdir /tmp/orca-out gcodes/cube_15x15x1.2.stl && cp /tmp/orca-out/plate_1.gcode gcodes/rf50_cube_pla.gcode
```

The print test turns Happy Hare's in-print gear sync off (`CI_MMU_PRINT_SYNC ENABLE=0`). With it on, batch mode
crashes in C (heap corruption in the step-generation path) once the gear follows the extruder. Field boxes run the
same Klipper commit and the same sync without crashing, so this looks batch-only; the root cause is still open.
