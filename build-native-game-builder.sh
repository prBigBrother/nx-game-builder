#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$ROOT/NativeGameBuilder"
OUTPUT="$ROOT/build/NX Game Builder.app"
TOOLCHAIN="$ROOT/build/bundled-toolchain"
if [[ ! -f "$TOOLCHAIN/manifest.json" || ! -f "$TOOLCHAIN/tools.tar.gz" ]]; then
    printf 'Prepare offline tools first: python3 scripts/prepare-bundled-toolchain.py --dotnet /path/to/dotnet\n' >&2
    exit 1
fi
printf 'Building the SwiftUI application…\n' 
swift build --package-path "$PROJECT" --scratch-path "$ROOT/build/swift-builder" -c release
BIN_DIR="$(swift build --package-path "$PROJECT" --scratch-path "$ROOT/build/swift-builder" -c release --show-bin-path)"
mkdir -p "$OUTPUT/Contents/MacOS" "$OUTPUT/Contents/Resources/Backend"
cp "$BIN_DIR/NXGameBuilder" "$OUTPUT/Contents/MacOS/NXGameBuilder"
cp "$PROJECT/Backend/"*.py "$PROJECT/Backend/"*.m "$PROJECT/Backend/"*.sh "$OUTPUT/Contents/Resources/Backend/"
cp "$PROJECT/Resources/"*.json "$OUTPUT/Contents/Resources/"
mkdir -p "$OUTPUT/Contents/Resources/Toolchain"
cp -c "$TOOLCHAIN/tools.tar.gz" "$OUTPUT/Contents/Resources/Toolchain/tools.tar.gz"
cp "$TOOLCHAIN/manifest.json" "$OUTPUT/Contents/Resources/Toolchain/manifest.json"
[[ -f "$ROOT/build/font-assets/standard.ttf" && -d "$ROOT/build/third-party-notices" ]] || { printf 'Prepare release fonts and notices first.\n' >&2; exit 1; }
mkdir -p "$OUTPUT/Contents/Resources/Fonts"
cp "$ROOT/build/font-assets/standard.ttf" "$ROOT/build/font-assets/nintendo_ext.ttf" "$OUTPUT/Contents/Resources/Fonts/"
cp "$PROJECT/Assets/Fonts/OFL.txt" "$OUTPUT/Contents/Resources/Fonts/"
ditto "$ROOT/build/third-party-notices" "$OUTPUT/Contents/Resources/Licenses"
cp "$ROOT/scripts/mac_app_icon.py" "$OUTPUT/Contents/Resources/Backend/"
python3 - "$ROOT" "$OUTPUT" "$(cat "$ROOT/VERSION")" <<'PY'
from pathlib import Path
import json, plistlib, sys
root, app = map(Path, sys.argv[1:3])
version = sys.argv[3]
defaults = dict(repository='', python='', dotnet='', keys='', work='',
                destination='/Applications', base='', update='', dlc=[], language='en-US', reuseExisting=True, importSaves=True)
(app / 'Contents/Resources/defaults.json').write_text(json.dumps(defaults))
info = dict(CFBundleExecutable='NXGameBuilder', CFBundleIdentifier='local.nxnative.gamebuilder',
            CFBundleName='NX Game Builder', CFBundleDisplayName='NX Game Builder', CFBundlePackageType='APPL',
            CFBundleShortVersionString=version, CFBundleVersion=version, LSMinimumSystemVersion='15.0',
            NSHighResolutionCapable=True, LSApplicationCategoryType='public.app-category.developer-tools')
with (app / 'Contents/Info.plist').open('wb') as stream: plistlib.dump(info, stream)
PY
python3 "$ROOT/scripts/mac_app_icon.py" "$OUTPUT" "$PROJECT/Assets/AppIcon.png"
codesign --verify --verbose "$OUTPUT"
printf '\nCreated: %s\n' "$OUTPUT"
if [[ "${1:-}" != --build-only ]]; then open "$OUTPUT"; fi
