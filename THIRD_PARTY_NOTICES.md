# Third-party notices

NX Game Builder's original SwiftUI application and packaging scripts are MIT licensed (see LICENSE). Bundled components retain their own licenses. No license in this project grants rights to game images, keys, DLC, publisher assets, or trademarks.

| Component | License / notices | Source |
| --- | --- | --- |
| nxnative (with the documented local shader-fetch patch) | MIT; upstream third-party notices are retained | https://github.com/seedds/nxnative |
| d2r-mobile, an upstream basis of nxnative | MIT | https://github.com/jhaizhou-ops/d2r-mobile |
| Ryujinx shader libraries / Spv.Generator | MIT; individual notices retained | Vendored by nxnative |
| libvpx | BSD-3-Clause and patent grant | Vendored by nxnative |
| stb_vorbis | MIT / public-domain dedication | Vendored by nxnative |
| Vulkan headers | MIT or Apache-2.0 | Vendored by nxnative |
| MacNativeGames / deko3d-derived code | MIT / zlib; file notices retained | Vendored by nxnative |
| CPython and python-build-standalone | PSF and included component licenses; build tooling has its own notices | https://github.com/python/cpython and https://github.com/astral-sh/python-build-standalone |
| Python packages | Individual wheel licenses retained in `.dist-info` and copied into the notices bundle | Exact versions in toolchain-versions.json |
| .NET SDK and LibHac | MIT and .NET ThirdPartyNotices | https://github.com/dotnet/sdk and the LibHac NuGet package |
| SPIRV-Cross / glslang / SPIRV-Tools | Apache-2.0 and included notices | KhronosGroup repositories |
| Zstandard / LZ4 / liblzma | BSD / BSD-2-Clause / 0BSD, with component notices | facebook/zstd, lz4/lz4, tukaani-project/xz |
| Noto CJK font software | SIL Open Font License 1.1 | https://github.com/notofonts/noto-cjk |

The runtime font **NX Game Sans** is a regular-weight static derivative of Noto Sans CJK JP. **NX Game Symbols** includes glyph outlines derived from the same OFL font and geometric controller-symbol shapes generated with nxnative's MIT tool. Modified fonts use new family names, preserve attribution, and are distributed under OFL-1.1 with `OFL.txt`. Apple/macOS fonts are not copied into generated apps.

The toolchain archive includes the original license files, embedded source notices and a component-version record. NX Game Builder and each newly generated game app also contain a readable `Contents/Resources/Licenses` directory. The game app's original game content remains subject to its owner's rights; runtime licenses do not license that content.

Some native tool binaries have their Mach-O load paths changed to use private bundled libraries and are ad-hoc re-signed. These are packaging changes, not a claim of upstream endorsement. The nxnative shader-fetch changes are recorded in `patches/nxnative.patch`. Full license texts and existing NOTICE/PATENTS files take precedence over this summary.

`RuntimeLicenses/PythonBuildComponents` retains the upstream Python-build component license collection (including OpenSSL, libffi, bzip2, libedit, SQLite, Tcl, zlib and others) and its source revision. It may also include notices for optional build components absent from this macOS runtime; inclusion does not assert that every listed component is linked.
