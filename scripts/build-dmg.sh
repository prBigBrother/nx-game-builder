#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cat "$ROOT/VERSION")"
APP="$ROOT/build/NX Game Builder.app"
[[ -d "$APP" ]] || { echo 'Build the app first.' >&2; exit 1; }
mkdir -p "$ROOT/dist"
STAGING="$(mktemp -d "$ROOT/build/dmg.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT
ditto "$APP" "$STAGING/NX Game Builder.app"
ln -s /Applications "$STAGING/Applications"
cp "$ROOT/LICENSE" "$ROOT/THIRD_PARTY_NOTICES.md" "$STAGING/"
cp "$ROOT/INSTALL.md" "$STAGING/Install.txt"
NAME="NX-Game-Builder-${VERSION}-arm64.dmg"
hdiutil create -volname 'NX Game Builder' -srcfolder "$STAGING" -ov -format UDZO "$ROOT/dist/$NAME"
hdiutil verify "$ROOT/dist/$NAME"
(cd "$ROOT/dist" && shasum -a 256 "$NAME" > "$NAME.sha256")
printf 'Created: %s\n' "$ROOT/dist/$NAME"
