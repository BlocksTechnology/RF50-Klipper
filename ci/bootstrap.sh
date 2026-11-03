#!/usr/bin/env bash
# Prepare ci/.cache: pinned Klipper fork (real + stub-beacon trees), Python venv, and one dict per RF50 MCU.
# Env: KLIPPER_SRC=<local clone> skips the network clone; CI_VENV=<venv> reuses one; CI_CACHE overrides .cache.
set -euo pipefail
CI=$(cd "$(dirname "$0")" && pwd)
# shellcheck source-path=SCRIPTDIR source=pins.env
. "$CI/pins.env"
C=${CI_CACHE:-$CI/.cache}
log() { echo "bootstrap: $*" >&2; }
# Subdirs of $C get rm -rf'd below: never adopt a non-empty CI_CACHE that bootstrap did not create.
if [ -n "${CI_CACHE:-}" ] && [ -n "$(ls -A "$C" 2>/dev/null)" ] && [ ! -f "$C/.rf50-ci-cache" ]; then
  log "refusing CI_CACHE=$C: not empty and not an RF50 CI cache"; exit 1
fi
mkdir -p "$C" && touch "$C/.rf50-ci-cache"

# 1. Klipper source at the pin, exported pristine (git archive ignores any working-copy edits).
SRC=${KLIPPER_SRC:-$C/src}
if [ ! -d "$SRC/.git" ]; then
  log "cloning $KLIPPER_URL"
  git clone --quiet --filter=blob:none --no-checkout "$KLIPPER_URL" "$SRC"
fi
git -C "$SRC" cat-file -e "$KLIPPER_REF^{commit}" 2>/dev/null || git -C "$SRC" fetch --quiet origin "$KLIPPER_REF"
VERSION=$(git -C "$SRC" describe --always --tags --long "$KLIPPER_REF")
for tree in klipper-real klipper-stub; do
  rm -rf "${C:?}/$tree" && mkdir -p "$C/$tree"
  git -C "$SRC" archive "$KLIPPER_REF" | tar -x -C "$C/$tree"
  echo "$VERSION" >"$C/$tree/klippy/.version"  # an archive has no .git for klippy's version lookup
  cp "$CI/klipper_plugins/"*.py "$C/$tree/klippy/extras/"
done
cp "$CI/stubs/beacon.py" "$C/klipper-stub/klippy/extras/beacon.py"
echo "$KLIPPER_REF" >"$C/klipper.ref"

# 2. Venv: the fork's own klippy requirements, plus numpy which beacon.py imports.
VENV=${CI_VENV:-$C/venv}
REQ=$C/klipper-real/scripts/klippy-requirements.txt
want=$( (cat "$REQ"; echo numpy) | sha256sum | cut -d' ' -f1)
[ -x "$VENV/bin/python" ] || { log "creating venv $VENV"; "$PYTHON" -m venv "$VENV"; }
# Stamp written only after pip succeeds, so a changed requirements file or a half-done install re-runs pip.
if [ "$(cat "$VENV/.rf50-ci-req" 2>/dev/null)" != "$want" ]; then
  log "installing klippy requirements into $VENV"
  "$VENV/bin/pip" install --quiet -r "$REQ" numpy
  echo "$want" >"$VENV/.rf50-ci-req"
fi
"$VENV/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 11), sys.version' || {
  log "venv must be Python 3.11 (the RF50 runs 3.11.2)"; exit 1; }
echo "$VENV" >"$C/venv.path"

# 3. Dicts: build each fork test/configs target once per pin, the way scripts/ci-build.sh does.
BUILT=$C/dicts-built/$KLIPPER_REF
mkdir -p "$BUILT"
build_dict() {
  local target=$1 fw=$C/fwbuild
  [ -s "$BUILT/$target.dict" ] && return
  log "building $target firmware dict"
  rm -rf "$fw" && mkdir -p "$fw"
  git -C "$SRC" archive "$KLIPPER_REF" | tar -x -C "$fw"
  echo "$VERSION" >"$fw/klippy/.version"
  cp "$fw/test/configs/$target.config" "$fw/.config"
  make -C "$fw" olddefconfig >/dev/null
  make -C "$fw" -j"$(nproc)" >"$C/build-$target.log" 2>&1 || { log "build failed, see $C/build-$target.log"; exit 1; }
  cp "$fw/out/klipper.dict" "$BUILT/$target.dict"
}

# .160-exact dicts (dicts/captured/<mcu>.dict, see README "MCU dicts") beat built ones.
D=$C/dicts
rm -rf "$D" && mkdir -p "$D"
for mcu in mcu Toolhead pi; do
  var=DICT_$mcu
  if [ -s "$CI/dicts/captured/$mcu.dict" ]; then
    cp "$CI/dicts/captured/$mcu.dict" "$D/$mcu.dict"; log "$mcu: captured dict"
  else
    build_dict "${!var}"; cp "$BUILT/${!var}.dict" "$D/$mcu.dict"; log "$mcu: built ${!var} dict"
  fi
done
if [ -s "$CI/dicts/captured/beacon.dict" ]; then
  cp "$CI/dicts/captured/beacon.dict" "$D/beacon.dict"; log "beacon: captured dict"
else
  # Beacon firmware is closed (encrypted dfu), so its dict is synthesised on an STM32 base.
  build_dict "$DICT_Toolhead"
  "$VENV/bin/python" "$CI/tools/mk_beacon_dict.py" "$BUILT/$DICT_Toolhead.dict" \
    "$CI/fidelity-rf50-160.json" "$D/beacon.dict" >&2
fi
log "ready: $C"
