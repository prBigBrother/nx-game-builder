# NX Game Builder

A macOS 15+ SwiftUI application that builds standalone game apps using nxnative. Apple silicon and Xcode with Metal Toolchain are required. Game images and keys are supplied by the user.

## Build the distribution

Prepare the offline toolchain on the development Mac, then build the app:

```bash
python3 scripts/prepare-bundled-toolchain.py --dotnet /path/to/dotnet
bash build-native-game-builder.sh --build-only
```

Preparation uses an existing relocatable uv Python 3.13, .NET SDK 10, and installed SPIRV-Cross, glslangValidator and zstd. Defaults match this workspace; `--python` and `--dotnet` select other runtime sources. The script copies tracked nxnative files, retaining this checkout's local game-profile/shader fixes. It includes LibHac's NuGet package for offline extraction-tool builds, relocates native utility dylibs, audits Mach-O dependencies and symlinks, and records component versions and notices. Package wheels are downloaded during distribution preparation, never on the end user's first launch. No game build is run.

The resulting `build/bundled-toolchain/tools.tar.gz` and `manifest.json` are included in `build/NX Game Builder.app`. The archive is approximately 307 MiB, unpacking to approximately 857 MiB for this snapshot. Exact sizes and SHA-256 are in the manifest. The app build fails if the offline archive is missing. It contains no developer-specific tool paths or default key path.

## First launch

1. Copy NX Game Builder.app to Applications and open it.
2. The setup assistant appears when no usable tool configuration is selected. Choose **Install bundled tools**. Settings → Toolchain → Setup assistant opens it again.
3. The archive is hash-checked and extracted locally with progress. Its Python modules, .NET SDK, native tools and shader translator are verified before activation. No network access, Homebrew or administrator access is needed for these bundled tools.
4. Install/open Xcode yourself and complete Apple's setup. The assistant detects Xcode and Metal and offers Apple's Metal Toolchain download when needed. These Apple components remain separate.
5. Select a game image and your local prod.keys. Keys are never bundled into the builder or the resulting game.

Writable tools live in `~/Library/Application Support/NX Game Builder/Tools/<bundle-id>/`. The bundle ID identifies the archive snapshot. Original app resources stay unchanged. Completed installations are reused; a new app toolchain snapshot gets a separate directory. A reinstall retains the replaced directory with a `.previous.<timestamp>` suffix. Existing selected external tools stay selected until installation succeeds or Use bundled tools is chosen. No local checkout is reset.

Installation cancellation stops the process group and removes its incomplete staging directory. Activation is transactional and checksums are verified before extraction. Setup logs are in `~/Library/Application Support/NX Game Builder/Logs/setup.log`.

`setup_tools.sh` remains as a developer fallback for builds without an embedded archive; normal distributions use `install_bundled_tools.sh`. It is not used to download dependencies in the bundled workflow.

## Build a game

In Build, select a base NSP/XCI/NSZ/XCZ, optional update NSP/NSZ and DLC, prod.keys, install folder and a language supported by the game. Choose **Build & Install**. NSZ/XCZ decompression is automatic and cached. The output `.app` includes real copies of RomFS, rewritten modules, fonts, DLC and Metal shaders; it does not depend on the builder or its toolchain at runtime.

The game stores saves, logs, temporary files and user pipeline data in `~/Library/Application Support/NXNative/<title-id>/`. Existing saves are imported only into an absent destination, never overwritten. First-use pipeline compilation may still cause a pause; recorded pipeline combinations can prewarm later launches.

Normal mode requires a registered nxnative profile/version. **Experimental games** surveys unregistered games, creates a provisional profile isolated by input fingerprint, refines memory settings after rewriting, runs the bounded heap check when needed, and attempts shader/app building. **Game report** opens the retained survey even after a later error. Successful packaging does not establish gameplay compatibility.

Backend subprocesses use the selected Python and private bin directory. Offline toolchains include a local NuGet feed for LibHac and disable NuGet auditing and .NET telemetry/development-certificate generation. The shader pipeline uses upstream `own_compilers.py`: Metal/SPIRV-Cross versions may differ from the maintainer's; missing tools and translator/source mismatches still stop the build.

## Interface and progress

The native sidebar contains Build, Settings and Log. Settings → Appearance → Interface language offers System (default), English and Русский. System uses Russian when the first macOS preferred language is `ru`, otherwise English. It applies immediately and is independent of game language. Compiler logs retain their original English output; filenames stay unchanged.

Overall progress in the window and Dock is a monotonic phase-weighted estimate, not elapsed-time prediction. Current-stage progress uses byte/file/shader counters where available. The Dock indicator clears on success, failure or cancellation. Offline setup uses archive entry counts while unpacking.

## Validation

```bash
python3 -m unittest discover -s NativeGameBuilder/Tests -v
swiftc NativeGameBuilder/Sources/NXGameBuilder/{BuildProgress,Localization,DockProgress}.swift NativeGameBuilder/Tests/UIModelChecks.swift -o build/ui-model-checks
./build/ui-model-checks
```

Tests cover packaging independence, external symlink rejection, font flags, safe replacement/rollback, save preservation, launcher relocation, provisional-profile reuse, compiler compatibility checks, offline checksum failure and installation transactions (including paths with spaces), and universal Mach-O parsing. Distribution preparation runs the copied runtimes and audits native dependencies. The real archive has been unpacked to a relocated path, and nx_extract built successfully from its local NuGet feed with a clean HOME/cache. Actual game compilation/gameplay still requires a user run; it is not part of distribution validation.

## Public releases and fonts

`VERSION` controls the app and DMG version. GitHub Actions builds on main/PRs and uploads a DMG plus SHA-256 to matching tag/releases. See the repository README and INSTALL.md for signing limitations.

`prepare-release-fonts.py` generates regular-weight NX Game Sans and controller-symbol fonts from the pinned OFL Noto CJK source. Both are distributed under OFL-1.1 with new names and retained attribution. No system font is read by game packaging. `collect-notices.py` collects nxnative, vendored, tool and font notices; each generated game app receives the readable notices bundle before signing. Settings → About links to the licenses and upstream project.
