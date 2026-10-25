#!/bin/bash
# Invoked by the native first-launch assistant. No administrator access or shell-profile changes.
set -euo pipefail
if [[ "${NX_SETUP_GROUP:-}" != 1 ]]; then
    export NX_SETUP_GROUP=1
    exec /usr/bin/perl -e 'setpgrp(0,0); exec @ARGV or die $!' /bin/bash "$0" "$@"
fi
ROOT="${1:?tool directory required}"
ACTION="${2:-install}"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"
stage() { printf '{"ev":"setup_stage","name":"%s","fraction":%s}\n' "$1" "$2"; }
fail() { printf '%s\n' "$1" >&2; exit 1; }
[[ "$(uname -m)" == arm64 ]] || fail 'Apple silicon is required.'
DEV="$(xcode-select -p 2>/dev/null || true)"
[[ "$DEV" == *Xcode*.app/Contents/Developer ]] || fail 'Install and open Xcode, then select it in Xcode Settings > Locations > Command Line Tools.'
if [[ "$ACTION" == metal ]]; then
    stage 'Downloading Metal Toolchain' 0.1
    exec xcodebuild -downloadComponent metalToolchain
fi
if [[ "$ACTION" == check ]]; then
    xcrun -sdk macosx metal --version
    exit
fi
xcrun -sdk macosx metal --version >/dev/null 2>&1 || fail 'Metal Toolchain is missing. Use Download Metal Toolchain first.'
mkdir -p "$ROOT/downloads" "$ROOT/bin" "$ROOT/sources"
# A lock directory prevents concurrent setup from another app instance.
if ! mkdir "$ROOT/.setup-lock" 2>/dev/null; then
    owner="$(cat "$ROOT/.setup-lock/pid" 2>/dev/null || true)"
    if [[ "$owner" =~ ^[0-9]+$ ]] && ! kill -0 "$owner" 2>/dev/null; then
        rm "$ROOT/.setup-lock/pid"
        rmdir "$ROOT/.setup-lock"
        mkdir "$ROOT/.setup-lock"
    else
        fail 'Another setup is already running.'
    fi
fi
printf '%s\n' "$$" > "$ROOT/.setup-lock/pid"
trap 'rm -f "$ROOT/.setup-lock/pid"; rmdir "$ROOT/.setup-lock" 2>/dev/null || true' EXIT
fetch() { /usr/bin/curl --fail --location --retry 3 --connect-timeout 30 --proto '=https' --tlsv1.2 "$1" -o "$2.partial"; mv "$2.partial" "$2"; }
checkout() {
    local url="$1" dir="$2" revision="$3"
    if [[ ! -d "$dir/.git" ]]; then
        [[ ! -e "$dir" ]] || fail "Unexpected existing folder: $dir"
        git init "$dir"
        git -C "$dir" remote add origin "$url"
    fi
    local actual="$(git -C "$dir" rev-parse HEAD 2>/dev/null || true)"
    if [[ "$actual" != "$revision" ]]; then
        [[ -z "$(git -C "$dir" status --porcelain)" ]] || fail "Local edits found in $dir; setup will not overwrite them."
        git -C "$dir" fetch --depth 1 origin "$revision"
        git -C "$dir" checkout --detach "$revision"
    fi
}
stage 'Downloading Python manager' 0.04
if [[ ! -x "$ROOT/bin/uv" ]]; then
    archive="$ROOT/downloads/uv-0.13.5.tar.gz"
    fetch 'https://github.com/astral-sh/uv/releases/download/0.13.5/uv-aarch64-apple-darwin.tar.gz' "$archive"
    printf '%s  %s\n' '743f85035a1996ecb350659e01cd9faea9709829be09b1b4b03c73eaf3c9cd73' "$archive" | shasum -a 256 -c -
    tar -xzf "$archive" -C "$ROOT/downloads"
    cp "$ROOT/downloads/uv-aarch64-apple-darwin/uv" "$ROOT/bin/uv"
fi
export UV_PYTHON_INSTALL_DIR="$ROOT/python" UV_CACHE_DIR="$ROOT/cache/uv" UV_PYTHON_BIN_DIR="$ROOT/bin"
stage 'Installing Python and dependencies' 0.14
"$ROOT/bin/uv" python install 3.14
if [[ ! -x "$ROOT/venv/bin/python" ]]; then "$ROOT/bin/uv" venv --python 3.14 --managed-python "$ROOT/venv"; fi
"$ROOT/bin/uv" pip install --python "$ROOT/venv/bin/python" capstone lz4 fonttools backports.zstd nsz cmake
export PATH="$ROOT/bin:$ROOT/venv/bin:$PATH"
stage 'Downloading .NET SDK 10' 0.29
if [[ ! -x "$ROOT/dotnet/dotnet" ]] || ! "$ROOT/dotnet/dotnet" --list-sdks | /usr/bin/grep -q '^10\.'; then
    fetch 'https://dot.net/v1/dotnet-install.sh' "$ROOT/downloads/dotnet-install.sh"
    bash "$ROOT/downloads/dotnet-install.sh" --channel 10.0 --architecture arm64 --install-dir "$ROOT/dotnet" --no-path
fi
export DOTNET_ROOT="$ROOT/dotnet" PATH="$ROOT/dotnet:$PATH"
stage 'Downloading nxnative' 0.43
checkout 'https://github.com/seedds/nxnative.git' "$ROOT/nxnative" '11be43d882f279fe27d0914c47f062bf80d7c867'
# Keep all source checkouts pinned; never pull or reset the user's selected checkout.
stage 'Building SPIRV-Cross' 0.56
checkout 'https://github.com/KhronosGroup/SPIRV-Cross.git' "$ROOT/sources/spirv-cross" '7affe74d77f93a622bb5002789d5332d32e512ee'
JOBS="$(sysctl -n hw.ncpu)"; [[ "$JOBS" -le 8 ]] || JOBS=8
if [[ ! -x "$ROOT/bin/spirv-cross" ]]; then
    cmake -S "$ROOT/sources/spirv-cross" -B "$ROOT/sources/spirv-cross/build" -DCMAKE_BUILD_TYPE=Release -DSPIRV_CROSS_ENABLE_TESTS=OFF
    cmake --build "$ROOT/sources/spirv-cross/build" --target spirv-cross --parallel "$JOBS"
    cp "$ROOT/sources/spirv-cross/build/spirv-cross" "$ROOT/bin/spirv-cross"
fi
stage 'Building GLSL compiler' 0.72
checkout 'https://github.com/KhronosGroup/glslang.git' "$ROOT/sources/glslang" 'e1b562a8bed273a02f30b59b66a5d499793cede5'
if [[ ! -x "$ROOT/bin/glslangValidator" ]]; then
    cmake -S "$ROOT/sources/glslang" -B "$ROOT/sources/glslang/build" -DCMAKE_BUILD_TYPE=Release -DENABLE_OPT=OFF -DENABLE_HLSL=OFF -DGLSLANG_TESTS=OFF
    cmake --build "$ROOT/sources/glslang/build" --target glslang-standalone --parallel "$JOBS"
    cp "$ROOT/sources/glslang/build/StandAlone/glslang" "$ROOT/bin/glslangValidator"
fi
stage 'Building Zstandard tools' 0.86
checkout 'https://github.com/facebook/zstd.git' "$ROOT/sources/zstd" 'f8745da6ff1ad1e7bab384bd1f9d742439278e99'
if [[ ! -x "$ROOT/bin/zstd" ]]; then
    make -C "$ROOT/sources/zstd" -j "$JOBS" zstd
    cp "$ROOT/sources/zstd/programs/zstd" "$ROOT/bin/zstd"
fi
stage 'Verifying installed tools' 0.96
"$ROOT/venv/bin/python" -c 'import capstone, lz4.block, fontTools, nsz'
"$ROOT/dotnet/dotnet" --list-sdks
"$ROOT/bin/glslangValidator" --version
"$ROOT/bin/zstd" --version
[[ -x "$ROOT/bin/spirv-cross" && -f "$ROOT/nxnative/dm/gfx/tools/dmsh_xlate_bin/dmsh_xlate.dll" ]] || fail 'Shader tools are incomplete.'
"$ROOT/venv/bin/python" - "$ROOT" <<'PY'
import hashlib, json, pathlib, subprocess, sys
root=pathlib.Path(sys.argv[1])
tools=root/'nxnative/dm/gfx/tools'
expected=hashlib.sha256(b''.join((tools/'dmsh_xlate'/n).read_bytes() for n in ('Program.cs','dmsh_xlate.csproj'))).hexdigest()[:16]
actual=subprocess.check_output([str(tools/'dmsh_xlate_bin/dmsh_xlate'),'--source-sha'],text=True).strip()
if actual != expected: raise SystemExit('The bundled shader translator does not match the pinned nxnative source.')
(root/'installed.json').write_text(json.dumps({'version':1,'nxnative':'11be43d882f279fe27d0914c47f062bf80d7c867'}))
PY
stage 'Build tools installed' 1
