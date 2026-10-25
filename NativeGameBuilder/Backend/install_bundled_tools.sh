#!/bin/bash
# Offline installation into a writable, versioned directory. No network commands.
set -euo pipefail
if [[ "${NX_SETUP_GROUP:-}" != 1 ]]; then
    export NX_SETUP_GROUP=1
    exec /usr/bin/perl -e 'setpgrp(0,0); exec @ARGV or die $!' /bin/bash "$0" "$@"
fi
ROOT="${1:?destination required}"
BUNDLE="${2:?bundle resources required}"
export PATH='/usr/bin:/bin:/usr/sbin:/sbin'
stage() { printf '{"ev":"setup_stage","name":"%s","fraction":%s}\n' "$1" "$2"; }
field() { /usr/bin/plutil -extract "$1" raw -o - "$BUNDLE/manifest.json"; }
[[ "$(uname -m)" == arm64 ]] || { echo 'Apple silicon is required.' >&2; exit 1; }
ID="$(field id)"; SHA="$(field sha256)"; ENTRIES="$(field entries)"; BYTES="$(field unpackedBytes)"
[[ "$ID" =~ ^[a-f0-9]{16}$ && "$SHA" =~ ^[a-f0-9]{64}$ && "$ENTRIES" =~ ^[0-9]+$ && "$BYTES" =~ ^[0-9]+$ ]] || exit 1
mkdir -p "$(dirname "$ROOT")"
LOCK="${ROOT}.install-lock"
if ! mkdir "$LOCK" 2>/dev/null; then
    owner="$(cat "$LOCK/pid" 2>/dev/null || true)"
    if [[ "$owner" =~ ^[0-9]+$ ]] && ! kill -0 "$owner" 2>/dev/null; then
        rm "$LOCK/pid"; rmdir "$LOCK"; mkdir "$LOCK"
    else echo 'Another tool installation is running.' >&2; exit 1; fi
fi
printf '%s\n' "$$" > "$LOCK/pid"
STAGING=''; BACKUP=''
cleanup() {
    if [[ -n "$BACKUP" && ! -e "$ROOT" ]]; then mv "$BACKUP" "$ROOT"; fi
    if [[ -n "$STAGING" && -d "$STAGING" ]]; then rm -rf "$STAGING"; fi
    rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null || true
}
trap cleanup EXIT
stage 'Verifying bundled tools' 0.02
printf '%s  %s\n' "$SHA" "$BUNDLE/tools.tar.gz" | shasum -a 256 -c -
FREE="$(df -Pk "$(dirname "$ROOT")" | awk 'END {print $4}')"
[[ "$FREE" -gt "$((BYTES / 1024 + 524288))" ]] || { echo 'Not enough free space to unpack build tools.' >&2; exit 1; }
STAGING="$(mktemp -d "${ROOT}.partial.XXXXXX")"
stage 'Unpacking bundled tools' 0.08
COPYFILE_DISABLE=1 tar -xzvf "$BUNDLE/tools.tar.gz" -C "$STAGING" 2>&1 | awk -v total="$ENTRIES" '
/^x / { count++; if (count % 100 == 0) { f=0.08+0.77*count/total; if(f>0.85) f=0.85; printf "{\"ev\":\"setup_stage\",\"name\":\"Unpacking bundled tools\",\"fraction\":%.4f}\n",f; fflush(); } next }
{ print; fflush(); }'
stage 'Verifying installed tools' 0.90
export PATH="$STAGING/bin:$PATH" DOTNET_ROOT="$STAGING/dotnet" PYTHONDONTWRITEBYTECODE=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_GENERATE_ASPNET_CERTIFICATE=false
"$STAGING/python/bin/python3.13" -c 'import capstone,lz4.block,fontTools,backports.zstd,nsz; print("Python modules verified")'
"$STAGING/dotnet/dotnet" --list-sdks
"$STAGING/bin/glslangValidator" --version
"$STAGING/bin/zstd" --version
"$STAGING/python/bin/python3.13" - "$STAGING" <<'PYTHON'
import hashlib, pathlib, subprocess, sys
root=pathlib.Path(sys.argv[1]); tools=root/'nxnative/dm/gfx/tools'
expected=hashlib.sha256(b''.join((tools/'dmsh_xlate'/n).read_bytes() for n in ('Program.cs','dmsh_xlate.csproj'))).hexdigest()[:16]
actual=subprocess.check_output([str(tools/'dmsh_xlate_bin/dmsh_xlate'),'--source-sha'],text=True).strip()
if actual != expected: raise SystemExit('Shader translator source mismatch')
print('Shader translator verified')
PYTHON
[[ -x "$STAGING/bin/spirv-cross" && -f "$STAGING/nxnative/scripts/build_ipa_from_nsp.py" ]] || exit 1
printf '{"version":2,"bundleID":"%s"}\n' "$ID" > "$STAGING/installed.json"
stage 'Activating bundled tools' 0.97
if [[ -e "$ROOT" ]]; then
    BACKUP="${ROOT}.previous.$(date +%s)"
    [[ ! -e "$BACKUP" ]] || exit 1
    mv "$ROOT" "$BACKUP"
fi
mv "$STAGING" "$ROOT"; STAGING=''
# Retain a replaced version for recovery; never discard local source edits.
stage 'Build tools installed' 1
