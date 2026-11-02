#!/usr/bin/env bash
# Run the RF50 batch-mode tests: the real config on the pinned Klipper fork, no hardware. Run bootstrap.sh first.
# Usage: run_tests.sh [tests/<tree>/<name>.test ...]   (default: every test plus the generated contract test)
# Config: CONFIG_DIR, else the repo this ci/ sits in, else CONFIG_REPO (~/dev/RF50-Klipper) at CONFIG_REF (origin/dev).
# Contract: BS_DIR (a BlocksScreen/ package dir), else BS_REPO (~/dev/BlocksScreen) at BS_REF (origin/dev).
set -uo pipefail
CI=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=pins.env
. "$CI/pins.env"
C=${CI_CACHE:-$CI/.cache}
TIMEOUT=${TEST_TIMEOUT:-120}  # test_klippy.py has none; a probe wait with no samples hangs forever
[ "$(cat "$C/klipper.ref" 2>/dev/null)" = "$KLIPPER_REF" ] || { echo "run_tests: cache missing or stale, run bootstrap.sh" >&2; exit 2; }
VENV=$(cat "$C/venv.path")
R=$C/run
rm -rf "$R" && mkdir -p "$R/config" "$R/gcodes" "$R/logs"

# Stage the config into a scratch copy so save_variables and friends never write to the source.
if [ -n "${CONFIG_DIR:-}" ]; then
  cp -a "$CONFIG_DIR/." "$R/config/"; src=$CONFIG_DIR
elif [ -f "$CI/../printer.cfg" ]; then
  tar -C "$CI/.." --exclude=./ci --exclude=./.git --exclude=./.ci-bs -cf - . | tar -x -C "$R/config"; src="$(cd "$CI/.." && pwd)"
else
  repo=${CONFIG_REPO:-$HOME/dev/RF50-Klipper} ref=${CONFIG_REF:-origin/dev}
  git -C "$repo" archive "$ref" | tar -x -C "$R/config"; src="$repo@$(git -C "$repo" rev-parse --short=8 "$ref")"
fi
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
if [ $# -eq 0 ]; then
  if [ -n "${BS_DIR:-}" ]; then bs=$BS_DIR; else
    bs=$R/bs; mkdir -p "$bs"
    git -C "${BS_REPO:-$HOME/dev/BlocksScreen}" archive "${BS_REF:-origin/dev}" BlocksScreen | tar -x -C "$bs"
    bs=$bs/BlocksScreen
  fi
  (cd "$CI/tools" && "$VENV/bin/python" contract_test.py "$bs" "$CI/contract_skip.txt" "$R/tests/real/contract.test")
  set -- "$R"/tests/*/*.test
else
  set -- "${@/#tests\//$R/tests/}"
fi

pass=0 fail=0
for t in "$@"; do
  tree=$(basename "$(dirname "$t")") name=$tree/$(basename "$t" .test)
  out=$R/logs/${name//\//_}.log
  rm -f "$C/klipper-$tree/_test_.log"
  (cd "$C/klipper-$tree" && timeout "$TIMEOUT" "$VENV/bin/python" scripts/test_klippy.py -k -d "$C/dicts" "$t") >"$out" 2>&1
  rc=$?
  # test_klippy only checks the exit code; '# CI_EXPECT_LOG: text' also pins WHY a SHOULD_FAIL test failed.
  expect=$(sed -n 's/^# CI_EXPECT_LOG: //p' "$t")
  if [ $rc -eq 0 ] && [ -n "$expect" ]; then
    cat "$C/klipper-$tree/_test_.log" >>"$out" 2>/dev/null
    grep -qF -- "$expect" "$out" || { rc=1; echo "CI: expected log line missing: $expect" >>"$out"; }
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
