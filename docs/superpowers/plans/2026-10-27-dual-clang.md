# Dual Clang Toolchains Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a Windows driver that explicitly selects external or Chromium LLVM and isolates static/shared builds.

**Architecture:** A Python standard-library CLI wraps the existing Chromium GN/autoninja workflow. Plan is offline and read-only; doctor aggregates prerequisites; configure and build require successful checks and maintain a provenance manifest.

**Tech Stack:** Python 3.10+, GN, depot_tools, clang-cl/lld-link, Visual Studio C++ tools, Windows SDK.

**Spec:** `docs/toolchain-design.md`

## Global Constraints

- External LLVM is the default; never silently fall back to Chromium LLVM.
- Windows x64 first; macOS/Linux execution is deferred.
- Keep upstream libc++, use local execution, preserve upstream plugins in Chromium mode.
- No automatic downloads or machine-wide installation.
- Outputs are separated by mode/linkage/configuration; an existing unrelated output must never be overwritten.
- Actual upstream compilation is not verified by mocked orchestration tests.

## Review Focus

- LLVM and checkout paths containing spaces or GN string metacharacters: escape in previews, reject unsupported upstream build paths in doctor.
- Missing external compiler while bundled compiler exists: fail without fallback.
- Existing output or modified arguments: preserve files and fail explicitly.
- Failed generation/build: propagate failure and do not leave success metadata.
- Changed source revision/compiler between configure/build: require reconfiguration in a fresh output.

### Task 1: Mode selection and offline planning

**Files:** `scripts/chromium_base.py`, `tests/test_chromium_base.py`, `.gitignore`.
**Interfaces:** CLI `plan --source PATH --toolchain external|chromium --llvm-root PATH --linkage static|shared --configuration release|debug`; JSON output describing args and output directory.

- [x] Write subprocess tests for default selection, bundled defaults, all output combinations, invalid mixed mode options, GN escaping, and no filesystem mutation.
- [x] Run `python -m unittest discover -s tests -v`; confirm missing CLI fails assertions.
- [x] Implement planning with standard-library argparse and pathlib.
- [x] Run tests and verify actual CLI output; combine the shared-file tasks into the final verified commit.

### Task 2: Prerequisite checks and guarded execution

**Files:** extend CLI and tests; add `README.md`, `.github/workflows/test.yml`.
**Interfaces:** `doctor`, `configure`, `build` use the same mode options plus `--depot-tools PATH` and optional `--gn PATH`. Doctor emits JSON and exits nonzero on missing prerequisites. Configure writes args/manifest only into owned output and executes GN. Build validates provenance then invokes autoninja for base.

- [x] Write tests for aggregated missing tools/no fallback, mismatched LLVM versions, foreign output preservation, tool failure propagation, altered arguments, and changed source/tool identity.
- [x] Observe failures, implement checks and guarded execution; mock only unavailable subprocess boundaries.
- [x] Run full suite and real doctor in both modes; record unmet host requirements.
- [x] Document use, checkout prerequisites, output limitations, and source/license obligations. Add Windows/Linux tests for the Python driver (not native library builds).
- [x] Request one fresh code review; fix material findings and rerun the suite.
- [x] Prepare the verified feature commit and report exact verification limits.

## Validation outcome

Windows / Python 3.11.14: 22 tests passed. Two review findings (conditional
Clang version detection and partial executable-path matching) were reproduced
and fixed with regression tests. Both real doctor modes correctly report missing
Chromium checkout, selected LLVM, GN, and depot_tools. VS 2026 and SDKs were found.
Approximately 25 GiB free space remains; native base builds, dependency extraction,
SDK packaging, and consumer-link validation have not been performed.
