# Dual LLVM toolchain design

Status: Approved in conversation on 2026-10-27, including both compiler modes.

## Intent and scope

Mirror Chromium base and its required dependencies to produce static and shared
libraries for Windows, macOS, and Linux. Start with Windows. The user selected
a separately installed LLVM clang-cl as the default, with an explicit optional
Chromium-provided clang-cl mode. Never silently fall back between them.

The source input is a standalone snapshot containing base and its required
dependencies, shared by BOTH compiler modes. A full Chromium checkout is not a
prerequisite. The 2026-10-27 driver's checkout-only assumption was an
implementation gap, corrected by the user's clarification on 2026-10-28.

Source synchronization has no compiler-mode option. One pinned source manifest
selects upstream paths and dependency revisions. Compiler acquisition is separate:
external LLVM is caller supplied; Chromium LLVM is a prebuilt package matching
the pinned source revision. Static/shared outputs remain separate.

## Approaches

- Chromium's bundled Clang: closest to upstream's tested configuration, but not
  the optional reference compiler distribution.
- External LLVM clang-cl: selected by the user. Requires an explicit LLVM path,
  disabled Chromium compiler plugins, and compiler/revision compatibility checks.
- MSVC cl.exe or MinGW: would require additional porting; not selected.

## Proposed defaults

- Initial target: Windows x64. ARM64 support is deferred.
- Keep upstream GN rules and use local builds, without remote execution.
- Use clang-cl and lld-link from the selected LLVM installation; upstream uses
  `lld-link /lib` for static archives.
- Native builds require source/LLVM paths without whitespace or shell
  metacharacters because upstream command construction does not quote all paths.
- In Chromium mode, use Chromium's matching prebuilt LLVM and upstream plugin defaults.
- In external mode, explicitly select LLVM and disable Chromium plugins.
- Use locally installed Visual Studio C++ tools and the Windows SDK.
- Retain Chromium's pinned libc++ initially. Consumer examples must use the same
  standard library and compatible compile definitions and runtime configuration.
- Separate output directories by compiler mode, linkage, and debug/release.
- Pin source SHA `1633b610f5957ddd13a26fe87628c0768067e740` and its dependency
  revisions. Its toolchain config requires Clang 24. Chromium LLVM and the shared
  Rust tools are separately downloaded binaries with locked SHA-256 checksums.
- Both compiler modes share this source model on Windows, macOS, and Linux.
  Native macOS/Linux build verification is deferred; Windows is the first target.

These defaults are recommendations, not additional user requirements.

## GN configuration shape

The following is a proposed configuration, not a tested build recipe. The LLVM
path must be supplied by the caller and validated; this example path does not
currently contain a detected LLVM installation.

```gn
target_cpu = "x64"
is_clang = true
clang_base_path = "C:/LLVM"
clang_use_chrome_plugins = false
use_remoteexec = false
use_lld = true
use_custom_libcxx = true
is_debug = false
is_component_build = false
```

The shared configuration changes `is_component_build` to `true`. Neither
configuration alone constitutes a self-contained distribution package.

## Environment observed on 2026-10-27

- Visual Studio Professional 2026, version 18.10.12201.205, is installed.
- Windows SDK include directories: 10.0.22621.0 and 10.0.26100.0.
- No clang-cl was found on PATH or at the standard LLVM locations checked.
  This is not an exhaustive search of all drives.
- Visual Studio C++ component completeness and the selected Chromium revision's
  SDK requirements still need verification.

## Acceptance and next implementation

The first driver supported only an existing full checkout; that is not the
intended final design. Replace this prerequisite with selective source extraction,
explicit provenance, a small standalone GN entry point, and separately acquired
build tools. No full checkout or Chrome/browser sources are required by design.
Do not equate source synchronization or driver tests with a successful native build.

1. Detect the caller-supplied LLVM installation, Visual Studio C++ components,
   and SDK; report missing tools without changing the machine automatically.
2. Pin a compatible Chromium/LLVM pair and generate separate GN arguments for
   static and shared builds.
3. Check generated compiler and linker commands actually use external LLVM.
4. Build both variants and compile/run consumer examples against the packaged
   headers and libraries outside the Chromium source tree.

The Windows x64 Chromium LLVM static target has built successfully. Shared-library
linking, external LLVM builds, packaging, and consumer ABI compatibility remain
unverified. Broad MSVC STL compatibility and a stable C ABI are not promised.

## Implementation evidence on 2026-10-28

- Selective extraction produced a Git-independent source tree; neither compiler
  mode requires a complete Chromium working tree.
- `source.lock.json` has no compiler mode. Both modes default to `vendor/chromium`.
- The first native GN attempt failed because SDK `10.0.28000.0` was absent.
  The user subsequently authorized installation. Microsoft's standalone SDK
  installer completed successfully, without restarting or closing the running VS.
  Headers, x86/x64/ARM64 libraries and rc.exe, UWP headers, and x64 dbghelp.dll were
  verified; rc.exe reports `10.0.28000.2526`.
- Standalone GN selects only `//:default` and its transitive dependencies through
  `root_patterns`, inherits the upstream directory-expansion allowlist, and
  disables JavaScript protobuf generation using `enable_js_protobuf=false`.
  The exporter generates `LASTCHANGE.committime` from the pinned commit.
- Windows dependency selection now includes BoringSSL, NASM, RE2, compiler-rt,
  LLVM libc support headers, GRIT, DebugVisualizers, and the Rust prelude's
  hmac-sha256 crate. All external repository revisions match Chromium DEPS.
- Chromium LLVM static GN generation passed: 847 targets from 317 files. Ninja's
  dry run passed with 2,346 steps. This checks declared build inputs; it does not
  by itself establish compilation, linking, or consumer ABI compatibility.
- Actual static compilation completed successfully after adding NASM autoconf
  headers and GoogleTest's production-only `gtest_prod.h`. The audit output is
  `vendor/chromium/out/dependency-audit/obj/base/base.lib` (5,591,220 bytes).
  Its `!<thin>` archive header means it references object files in the build tree;
  it is not a standalone distribution package. Shared GN generation also passed
  (856 targets from 318 files), and its Ninja dry run passed with 2,275 steps,
  without claiming a completed DLL build. Both managed configurations were
  regenerated after the final header additions and match the verified inventory.
- LLVM, GN, Ninja and Rust live outside the source snapshot. Rust package identity
  is checked against the lock rather than inferred from a version label alone.

## References

- https://chromium.googlesource.com/chromium/src/+/main/docs/clang.md
- https://github.com/chromium/chromium/blob/main/build/config/clang/clang.gni
- https://github.com/chromium/chromium/blob/main/build/config/c%2B%2B/c%2B%2B.gni
