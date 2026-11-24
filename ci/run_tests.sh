#!/usr/bin/env bash
# Run the RF50 batch-mode tests: the real config on the pinned Klipper fork, no hardware. Run bootstrap.sh first.
# Usage: run_tests.sh [path/to/<tree>/<name>.test ...]   (default: every test plus the generated contract test)
# Config: CONFIG_DIR, else the repo this ci/ sits in, else CONFIG_REPO (~/dev/RF50-Klipper) at CONFIG_REF (origin/dev).
# Contract: BS_DIR (a BlocksScreen/ package dir), else BS_REPO (~/dev/BlocksScreen) at BS_REF (origin/dev).
set -uo pipefail
CI=$(cd "$(dirname "$0")" && pwd)
# shellcheck source-path=SCRIPTDIR source=pins.env
. "$CI/pins.env"
C=${CI_CACHE:-$CI/.cache}
TIMEOUT=${TEST_TIMEOUT:-120}  # test_klippy.py has none; a probe wait with no samples hangs forever
[ "$(cat "$C/klipper.ref" 2>/dev/null)" = "$KLIPPER_REF" ] || { echo "run_tests: cache missing or stale, run bootstrap.sh" >&2; exit 2; }
VENV=$(cat "$C/venv.path")
R=$C/run
# Resolve test args now (the runs below cd into the klipper tree); ci/tests/* runs from the staged copy beside ci.cfg.
tests=()
for t in "$@"; do
  p=$(realpath -e "$t") || { echo "run_tests: no such test: $t" >&2; exit 2; }
  tests+=("${p/#"$CI"\/tests\//$R/tests/}")
done
rm -rf "${R:?}" && mkdir -p "$R/config" "$R/gcodes" "$R/logs"
cp "$CI"/gcodes/*.gcode "$R/gcodes/"  # virtual_sdcard root, for SDCARD_PRINT_FILE tests

# Re-sync the CI plugins every run so an edit to them never tests a stale copy from the last bootstrap.
for tree in klipper-real klipper-stub; do cp "$CI/klipper_plugins/"*.py "$C/$tree/klippy/extras/"; done
cp "$CI/stubs/beacon.py" "$C/klipper-stub/klippy/extras/beacon.py"

# Stage the config into a scratch copy so save_variables and friends never write to the source.
stage() { tar -C "$1" --exclude=./ci --exclude=./.git --exclude=./.ci-bs -cf - . | tar -x -C "$R/config"; }
if [ -n "${CONFIG_DIR:-}" ]; then
  stage "$CONFIG_DIR" || exit 2; src=$CONFIG_DIR
elif [ -f "$CI/../printer.cfg" ]; then
  stage "$CI/.." || exit 2; src="$(cd "$CI/.." && pwd)"
else
  repo=${CONFIG_REPO:-$HOME/dev/RF50-Klipper} ref=${CONFIG_REF:-origin/dev}
  git -C "$repo" archive "$ref" | tar -x -C "$R/config" || { echo "run_tests: cannot export $repo@$ref" >&2; exit 2; }
  src="$repo@$(git -C "$repo" rev-parse --short=8 "$ref")"
fi
[ -f "$R/config/printer.cfg" ] || { echo "run_tests: no printer.cfg in $src" >&2; exit 2; }
echo "run_tests: config $src, klipper ${KLIPPER_REF:0:8}"
cp "$R/config/variables.cfg" "$R/vars.cfg" 2>/dev/null || : >"$R/vars.cfg"

# Wrapper: CI plugin first, then the machine config, then batch-only overrides (later sections win).
cat >"$R/ci.cfg" <<EOF
[ci_batch_shims]
[include config/printer.cfg]
[mcu]
canbus_uuid: 000000000001
[mcu Toolhead]
canbus_uuid: 000000000002
[save_variables]
filename: $R/vars.cfg
[virtual_sdcard]
path: $R/gcodes
EOF

cp -a "$CI/tests" "$R/tests"
pass=0 fail=0
if [ ${#tests[@]} -eq 0 ]; then
  if [ -n "${BS_DIR:-}" ]; then
    bs=$BS_DIR bs_rev=$(git -C "$bs" rev-parse --short=8 HEAD 2>/dev/null || echo "unknown rev")
  else
    bs=$R/bs bs_repo=${BS_REPO:-$HOME/dev/BlocksScreen} bs_ref=${BS_REF:-origin/dev}; mkdir -p "$bs"
    git -C "$bs_repo" archive "$bs_ref" BlocksScreen | tar -x -C "$bs" \
      || { echo "run_tests: cannot export BlocksScreen $bs_ref" >&2; exit 2; }
    # Read the rev from the source repo: under ci/.cache, git -C on the export finds this repo's HEAD.
    bs=$bs/BlocksScreen bs_rev="$bs_ref $(git -C "$bs_repo" rev-parse --short=8 "$bs_ref")"
  fi
  echo "run_tests: contract from $bs ($bs_rev)"
  # A missing or broken contract must fail the run, never just drop the test.
  if (cd "$CI/tools" && "$VENV/bin/python" contract_test.py "$bs" "$CI/contract_skip.txt" "$CI/contract_extra.txt" \
      "$R/tests/real/contract.test"); then :; else
    fail=$((fail + 1)); echo "FAIL real/contract (generator, see contract: ERROR lines above)"
  fi
  tests=("$R"/tests/*/*.test)
fi

# Klippy log minus the "===== Config file =====" dumps, so an expect line can only match runtime output.
runtime_log() { awk '/^===== Config file =====$/{d=1; next} d && /^=+$/{d=0; next} !d' "$1"; }

for t in "${tests[@]}"; do
  tree=$(basename "$(dirname "$t")") name=$tree/$(basename "$t" .test)
  out=$R/logs/${name//\//_}.log
  rm -f "$C/klipper-$tree/_test_.log"
  (cd "$C/klipper-$tree" && timeout "$TIMEOUT" "$VENV/bin/python" scripts/test_klippy.py -k -d "$C/dicts" "$t") >"$out" 2>&1
  rc=$?
  # test_klippy only checks the exit code; each '# CI_EXPECT_LOG: text' line also pins WHY a SHOULD_FAIL test failed.
  if [ $rc -eq 0 ] && grep -q '^# CI_EXPECT_LOG: ' "$t"; then
    cat "$C/klipper-$tree/_test_.log" >>"$out" 2>/dev/null
    rt=$(runtime_log "$out")  # filter once: 'awk | grep -q' under pipefail fails on an early match (awk SIGPIPE)
    while IFS= read -r expect; do
      grep -qF -- "$expect" <<<"$rt" || { rc=1; echo "CI: expected log line missing: $expect" >>"$out"; }
    done < <(sed -n 's/^# CI_EXPECT_LOG: //p' "$t")
  fi
  if [ $rc -eq 0 ]; then pass=$((pass + 1)); echo "PASS $name"; continue; fi
  fail=$((fail + 1))
  [ $rc -eq 124 ] && echo "FAIL $name (timeout ${TIMEOUT}s)" || echo "FAIL $name"
  grep -E "^(!!|Config error|Error|.*Error:|CI: |Unknown command)" "$out" | grep -v -e "^Error during test" -e "git version" -e "FileNotFoundError" -e "Error running git" | sort -u | head -5 | sed 's/^/     /'
  echo "     log: $out"
done
"$VENV/bin/python" "$CI/tools/fidelity.py" "$C/dicts" "$CI/fidelity-rf50-160.json"
echo "run_tests: $pass passed, $fail failed"
[ $fail -eq 0 ]
