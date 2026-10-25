#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "$(uname -m)" == arm64 ]] || { echo 'An arm64 runner is required.' >&2; exit 1; }
if [[ ! -d "$ROOT/.nxnative/.git" ]]; then
    git init "$ROOT/.nxnative"
    git -C "$ROOT/.nxnative" remote add origin https://github.com/seedds/nxnative.git
    git -C "$ROOT/.nxnative" fetch --depth 1 origin 11be43d882f279fe27d0914c47f062bf80d7c867
    git -C "$ROOT/.nxnative" checkout --detach FETCH_HEAD
    git -C "$ROOT/.nxnative" apply "$ROOT/patches/nxnative.patch"
fi
uv python install 3.13.12
PYTHON_ROOT="$(uv python find 3.13.12 --managed-python)"
PYTHON_ROOT="$(dirname "$(dirname "$PYTHON_ROOT")")"
python3 "$ROOT/scripts/prepare-bundled-toolchain.py" --python "$PYTHON_ROOT" --dotnet "${DOTNET_ROOT:?setup-dotnet must set DOTNET_ROOT}" --repository "$ROOT/.nxnative"
