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
| `tests/stub/` | runs with `stubs/beacon.py`; motion needs it (real Beacon waits for samples batch mode never sends) |
| `klipper_plugins/ci_batch_shims.py` | CI-only extra: unknown command = error, `CI_ASSERT_COMMANDS`, aht10/beacon connect no-ops |
| `contract_skip.txt` | BlocksScreen commands the config may lack, each with a reason |
| `tools/fidelity.py` | CI dicts vs live .160 constants, report only |
| `dicts/captured/<mcu>.dict` | real dicts from `rf50_capture.py dump`; replace the generic builds when present |

Not covered yet: AMU variant (`MMU_*`, mmu MCU), print core (`CHANGE_PRINTCORES`, WIP), real MCU dicts (built
from Klipper's generic test configs: 130 msgs vs 136-138 live, Toolhead PWM_MAX 32768 vs 257).
A `# CI_EXPECT_LOG: text` line in a `.test` makes the runner also require that text in the log, so a
SHOULD_FAIL test cannot pass for the wrong reason.
