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
- [x] Synchronize real selected sources: final snapshot has 27,495 files / approximately 249 MiB. File checksums and all installed tool payloads were verified; rustc --version also executed successfully.
- [ ] Resolve remaining build dependencies using GN after the missing SDK is installed.

### Task 2: Standalone GN entry and build driver

Files: `standalone/`, `scripts/chromium_base.py`, tests.
- [x] Test Git-independent source identity shared by both compiler modes.
- [x] Replace checkout-specific prerequisites with snapshot validation and standalone root.
- [x] Acquire needed tools separately and attempt native GN generation; SDK 10.0.28000.0 is missing, so compilation cannot start.

### Task 3: Verification and documentation

Files: `README.md`, design and plan.
- [x] Remove full-checkout instructions from the intended workflow.
- [x] Run full tests and one independent code review, fix material findings. 36 tests passed, including an actual Windows directory junction regression; follow-up review found no remaining Important issue in the fixes.
- [x] Record this implementation checkpoint in a local commit with the source/build validation status below; native build work remains blocked on SDK approval.

## Native validation blocker

On 2026-10-28, GN entered `//base/BUILD.gn` and failed in
`build/toolchain/win/setup_toolchain.py`: the environment's include path
`C:/Program Files (x86)/Windows Kits/10/include/10.0.28000.0/um` does not exist.
The first real snapshot contained 27,121 files / 258,322,557 bytes. Tool downloads
are separate from it. The final lock includes the transitive dependencies of 37
Rust crate wrappers. Source dependency closure is explicitly NOT marked complete.

System SDK installation approval is pending. No native library build, packaging,
or consumer ABI success is claimed.
