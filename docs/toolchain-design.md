# Dual LLVM toolchain design

Status: Approved in conversation on 2026-10-27, including both compiler modes.

## Intent and scope

Mirror Chromium base and its required dependencies to produce static and shared
libraries for Windows, macOS, and Linux. Start with Windows. The user selected
a separately installed LLVM clang-cl as the default, with an explicit optional
Chromium-provided clang-cl mode. Never silently fall back between them.

This document covers the initial toolchain configuration, not a complete design
for dependency extraction or library packaging.

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
- Native builds require checkout/LLVM paths without whitespace or shell
  metacharacters because upstream command construction does not quote all paths.
- In Chromium mode, use the checkout's bundled LLVM and upstream plugin defaults.
- In external mode, explicitly select LLVM and disable Chromium plugins.
- Use locally installed Visual Studio C++ tools and the Windows SDK.
- Retain Chromium's pinned libc++ initially. Consumer examples must use the same
  standard library and compatible compile definitions and runtime configuration.
- Separate output directories by compiler mode, linkage, and debug/release.
- Record the exact LLVM version and Chromium commit after compatibility checks;
  neither has been selected or validated yet.
- Later macOS/Linux builds will use external Clang with platform-specific SDKs
  and configuration. Windows binaries are not portable across operating systems.

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

Implementation scope for this step: a Windows build driver with plan, doctor,
configure, and build commands for an existing synchronized Chromium checkout.
The machine has approximately 25 GiB free and no detected LLVM or Chromium
checkout. Downloading a full checkout and proving actual base compilation remain
environment-dependent follow-up work. Do not equate driver tests with a base build.

1. Detect the caller-supplied LLVM installation, Visual Studio C++ components,
   and SDK; report missing tools without changing the machine automatically.
2. Pin a compatible Chromium/LLVM pair and generate separate GN arguments for
   static and shared builds.
3. Check generated compiler and linker commands actually use external LLVM.
4. Build both variants and compile/run consumer examples against the packaged
   headers and libraries outside the Chromium source tree.

Library builds and ABI compatibility have not been validated. Broad MSVC STL
consumer compatibility and a stable C ABI are not promised by this configuration.

## References

- https://chromium.googlesource.com/chromium/src/+/main/docs/clang.md
- https://github.com/chromium/chromium/blob/main/build/config/clang/clang.gni
- https://github.com/chromium/chromium/blob/main/build/config/c%2B%2B/c%2B%2B.gni
