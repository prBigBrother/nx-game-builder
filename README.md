# NX Game Builder

Native SwiftUI app for building standalone macOS game apps with [nxnative](https://github.com/seedds/nxnative).

**Apple silicon · macOS 15 or newer · Xcode + Metal Toolchain for game builds**

## Download

Download the Apple silicon DMG from [GitHub Releases](https://github.com/prBigBrother/nx-game-builder/releases/latest), open it, and drag NX Game Builder into Applications. Checksums accompany each DMG.

The default releases are **ad-hoc signed, not Developer ID signed or notarized**. macOS may require a manual first-launch decision in Privacy & Security. The app does not disable security protections. See [installation instructions](INSTALL.md).

## Features

- Native sidebar, English/Russian interface, automatic system-language selection.
- Base NSP/XCI/NSZ/XCZ, optional updates and DLC.
- Offline toolchain included: portable Python and dependencies, .NET SDK 10, nxnative, shader/compression utilities and private libraries.
- First-launch setup extracts and verifies tools locally, with progress and cancellation.
- Standalone game `.app` bundles with resources, DLC, compiled shaders, OFL fonts and runtime license notices.
- Current-stage progress and estimated overall progress in the window and Dock.
- Experimental survey/profile generation for games not registered in nxnative. Packaging success does not guarantee gameplay compatibility.

Game compatibility comes from the pinned nxnative version and its profiles. Game images, keys, firmware, DLC and saves are **not** included in this repository or releases. Supply your own inputs and ensure you have the required rights; this project's licenses do not license publisher game content.

## Build from source

The distribution is built on Apple silicon. On the development machine, install Xcode, .NET SDK 10.0.402, uv, and the Homebrew packages `spirv-cross glslang zstd`, then run:

```bash
export DOTNET_ROOT=/path/to/dotnet
bash scripts/ci-prepare-tools.sh
bash build-native-game-builder.sh --build-only
bash scripts/build-dmg.sh
```

This checks out nxnative at `11be43d882f279fe27d0914c47f062bf80d7c867`, applies the documented shader-fetch patch and prepares the bundled runtime, fonts and notices. Generated archives stay out of Git. The original nxnative MIT and third-party licenses are preserved; our wrapper and scripts are MIT licensed.

Details: [application documentation](NativeGameBuilder/README.md), [third-party notices](THIRD_PARTY_NOTICES.md), [MIT license](LICENSE).

## Automated releases

The GitHub Actions workflow tests and builds the app and DMG on `macos-15` arm64. Main-branch pushes and pull requests provide build artifacts. To publish a version:

1. Update `VERSION` and `RELEASE_NOTES.md` and merge the changes.
2. Push a matching tag, such as `v1.2.0`, or publish a GitHub Release for that tag.
3. Actions builds the DMG and SHA-256 file, then uploads them to the release.

Only the publish job has repository write access. Release tags must match `VERSION`. No signing credentials are required for the default ad-hoc build. Apple Developer ID signing/notarization is not configured.

## Acknowledgements

Powered by seedds/nxnative, itself based in part on d2r-mobile and the libraries listed in its third-party documentation. Text and controller-symbol fonts are generated from Noto CJK under SIL OFL, with new derivative names. No Apple system fonts are redistributed.
