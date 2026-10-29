# Static SDK export implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan inline.

**Goal:** Export the existing Windows x64 static base build as ordinary archives, source/generated headers, and a relocatable CMake import target.

**Architecture:** Generate a separate GN consumer contract under the snapshot's excluded `out/` directory, using the original build arguments. GN JSON plus Ninja's expanded link command supplies consumer configuration and actual link inputs; no per-version library list or Chromium source patch. Convert thin archives using the selected LLVM librarian, preserve required object/library inputs and licenses, and publish atomically with provenance.

**Tech Stack:** Python 3.10+, upstream GN/Ninja, clang-cl/lld-link, CMake.

**Spec:** `docs/toolchain-design.md`; user explicitly requested archive/header/dependency integration before the sample project on 2026-10-28.

## Global constraints

- Same selected source snapshot for external and Chromium LLVM; never fall back between compilers.
- No complete Chromium checkout and no edits to upstream source/build rules.
- Initial export is Windows x64 static Release with pinned libc++; reject unsupported configurations clearly.
- A relocated SDK must compile/link/run a separate consumer without reading the original source or build directories.
- Existing destinations and original build artifacts must be preserved.
- Continue in the existing clean feature branch and workspace, reusing its large verified native build; no additional checkout.

## Review focus

- Host tools or unrelated graph nodes accidentally included in runtime link inputs.
- Source/build absolute paths or thin-archive object references surviving relocation.
- Missing generated/extensionless headers and licenses.
- CRT/libc++ ABI mismatch or internal BASE_IMPLEMENTATION definitions leaking to consumers.
- Malformed paths, command parsing, unsupported configuration, and partial export failures.

### Task 1: Discover a consumer contract

Files: `scripts/sdk_metadata.py`, `tests/test_sdk_metadata.py`.
- [x] Inspect real GN JSON and expanded Ninja link command for an isolated probe target.
- [x] Add failing tests for Windows quoting, path rebasing, runtime input selection, and configuration rejection.
- [x] Implement contract discovery from generated metadata, without a maintained dependency list.
- [x] Run tests and inspect the real exported contract.

### Task 2: Export ordinary archives and relocatable CMake package

Files: `scripts/export_sdk.py`, `cmake/`, `tests/test_export_sdk.py`.
- [x] Test preservation of existing destinations, header layout, relocation, and archive conversion failures.
- [x] Stage regular archives, required objects, headers, licenses, and provenance; reject remaining thin archives.
- [x] Generate `ChromiumBaseConfig.cmake`, target `ChromiumBase::base`, and an explicit LLVM toolchain file.
- [x] Publish only after validation; verify the real package has no original-source/build path references in its usage contract.

### Task 3: Consumer verification and documentation

Files: `tests/sdk_consumer/`, `README.md`, this plan.
- [x] Build/run a small external validation consumer using strings, JSON, files, and a task runner (verification fixture, not the requested sample project).
- [x] Relocate the SDK and verify compiler dependency output refers only to the relocated SDK, compiler, and system SDK.
- [x] Run unit tests; obtain final independent code review and address material findings.
- [x] Record actual supported/untested modes and commit the implementation.

## Ledger

- User authorized this groundwork first; no further sample-design approval is needed for the exporter and verification fixture.
- Existing feature branch: `feat/dual-clang-toolchains`, starting commit `9e37e41`.
- The reusable native build is `vendor/chromium/out/dependency-audit`; its base archive is thin. Managed static/shared directories are configured but not compiled.
- GN supports `--root-target` and `--root-pattern` overrides without changing the source root or upstream files.
- Native export: 579 runtime inputs = 95 `.lib`, 26 `.rlib`, 458 direct `.obj`; every archive has `!<arch>` magic and verified payload hash.
- The installed lld crashes when reading base's thin archive as librarian input. Rebuilding ordinary archives from exact Ninja alink input lists succeeds; no upstream patches. All 97 alink commands / 1,407 members parsed, including NASM `.o` members.
- CMake needs `/lib` as the first lld argument; shipped make-rule override enforces this. Imported target `SYSTEM FALSE` preserves GN's `-I` precedence so libc++ C wrappers precede compiler/system headers.
- SDK relocated to `out/sdk/relocated sdk/windows-x64-chromium-static-release`. Verification fixture copied outside source tree; its own static library and executable compiled/linked/ran successfully with CMake 4.3 and pinned Clang 24.
- Final evidence: `.cache/sdk/consumer-verification-4/verification.json`, configure/build/execute/dependencies/commands logs. 2,315 real header dependency entries restricted to relocated SDK, fixture, LLVM and VS/Windows SDK includes; no original source/build references.
- During development the successful native export's CMake metadata was refreshed through `package_config` after the rule fixes; package file hashes were updated. Original native artifact hashes remained unchanged.
- Full Python suite: 53 tests passed. Independent review found missing source plan field and unsupported sanitizer arguments; both fixed with regressions. Autoninja identity reproduction remains outside this exporter's direct-Ninja scope and is explicitly rejected/documented.
- Debug, shared SDKs, macOS/Linux and external LLVM native builds remain unverified. No channel-selection automation or end-user sample added in this task.
- Final review caught imported-target scope mismatch with the global include guard. Sibling `find_package` fixture reproduced failure (verification 3); `IMPORTED GLOBAL` fixed it and full native verification 4 passed. Reviewer confirmed no remaining material findings. C++-only consumer-target scope documented.
- SDK: 10,017 files, 418,005,317 bytes (~399 MiB). Original base thin archive still matches pre-export SHA-256 `91af536d04fe565294808e3ef2187173e79b0449a69f5f039fceb406f1ec8b54`.
