# Shared Standalone Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the full-checkout prerequisite with one selectively extracted base/dependency snapshot shared by external and Chromium LLVM.

**Architecture:** A pinned manifest selects Chromium directories and dependency Git revisions; a partial Git cache fetches only selected blobs without populating a working tree. Export a Git-independent snapshot with a file inventory and minimal GN entry point. Source sync is independent of toolchain selection; tools are separate downloads.

**Tech Stack:** Python standard library, Git partial clone/object export, GN, Ninja, Windows LLVM.

**Spec:** `docs/toolchain-design.md`, corrected source requirement approved by user on 2026-10-28.

## Global Constraints

- Never fetch a full Chromium working tree or require one from the user.
- Both compiler modes consume the same source manifest and source directory.
- Preserve upstream licenses and path structure; isolate standalone build overlays.
- Pin full Git SHAs and download checksums; do not silently follow main after locking.
- Do not claim dependency closure or native build success until GN/build validates it.

## Review Focus

- Path traversal and output overwrites during source extraction.
- Unpinned dependencies or accidental fetching of browser/renderer trees.
- Git-less snapshot identity and edit detection.
- Source sync accidentally depending on selected compiler.
- Tool downloads and generated configuration entering the source inventory.

### Task 1: Source manifest and selective synchronization

Files: `source.lock.json`, `scripts/sync_source.py`, `tests/test_sync_source.py`.
- [x] Test path/revision validation, source-only selection, safe extraction, provenance, and existing output protection.
- [x] Implement selective Git export and locked dependencies.
- [x] Synchronize real selected sources: dependency-complete GN snapshot has 34,706 files / 377,842,355 bytes (approximately 360 MiB). File checksums and installed tool payloads were verified; rustc --version also executed successfully.
- [x] Resolve remaining Windows static build dependencies using GN: 847 targets generated and Ninja dry run passed with 2,346 steps. Compilation/linking is a separate validation step.

### Task 2: Standalone GN entry and build driver

Files: `standalone/`, `scripts/chromium_base.py`, tests.
- [x] Test Git-independent source identity shared by both compiler modes.
- [x] Replace checkout-specific prerequisites with snapshot validation and standalone root.
- [x] Acquire needed tools separately and attempt native GN generation; the initial SDK blocker was resolved by installing SDK 10.0.28000.0 with user approval.

### Task 3: Verification and documentation

Files: `README.md`, design and plan.
- [x] Remove full-checkout instructions from the intended workflow.
- [x] Run full tests and one independent code review, fix material findings. 36 tests passed, including an actual Windows directory junction regression; follow-up review found no remaining Important issue in the fixes.
- [x] Record the source-extraction implementation checkpoint in a local commit with its validation status; native dependency closure remains outstanding.

## Native validation status

On 2026-10-28, GN entered `//base/BUILD.gn` and failed in
`build/toolchain/win/setup_toolchain.py`: the environment's include path
`C:/Program Files (x86)/Windows Kits/10/include/10.0.28000.0/um` does not exist.
The first real snapshot contained 27,121 files / 258,322,557 bytes. Tool downloads
are separate from it. The final lock includes the transitive dependencies of 37
Rust crate wrappers. Source dependency closure is explicitly NOT marked complete.

The user authorized SDK installation on 2026-10-28. The VS installer was blocked
by an open VS process, so Microsoft's standalone SDK installer was used instead.
It completed with exit code 0 and no restart. SDK 10.0.28000.0 headers, libraries,
and tools for x86/x64/ARM64, UWP headers, and x64 dbghelp.dll were verified.
rc.exe reports 10.0.28000.2526. No native library build, packaging, or consumer ABI
success is claimed. GN was rerun with the SDK present: SDK setup passed, then
`third_party/protobuf/proto_library.gni:170` failed to import
`third_party/closure_compiler/compile_js.gni`. This is the next source-selection
gap to resolve, not an SDK installation failure.

The subsequent dependency pass resolved that gap using the supported
`enable_js_protobuf=false` option, a narrowly selected GN root, and upstream
directory-expansion settings. It added the required BoringSSL, NASM, RE2,
compiler-rt, LLVM libc headers, GRIT, DebugVisualizers, and hmac-sha256 inputs to
the common source lock. The exporter now generates the build timestamp from the
pinned commit. Static GN generation and Ninja's input dry run both passed.
The full compiler/linker validation is tracked separately from this GN result.
Actual compilation additionally identified NASM's `autoconf` headers and
GoogleTest's production-only `gtest_prod.h`; both are now pinned in the lock.
The resumed Ninja static build exited 0 and produced a 5,591,220-byte `base.lib`
at `vendor/chromium/out/dependency-audit/obj/base/base.lib`. Its archive signature
is `!<thin>`, so object files and transitive dependencies still need packaging.
Shared GN generation passed with 856 targets from 318 files and its Ninja dry
run passed with 2,275 steps. Both managed configurations match the final verified
source inventory. A DLL build and external LLVM native validation are not claimed.
