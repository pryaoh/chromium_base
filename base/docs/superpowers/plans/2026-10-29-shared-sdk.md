# Shared SDK verification implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline; obtain one final independent review.

**Goal:** Actually build Windows x64 Chromium LLVM component DLLs, export their consumer contract, and run the existing sample against the deployed DLLs.

**Architecture:** Reuse the configured managed shared build and the existing GN/Ninja-driven exporter. Obtain runtime dependencies from GN, retain import libraries and component consumer flags, generate an MD-compatible CMake package, and deploy runtime files beside executables. Verify PE imports plus execution from a separate deployment directory without the original build on PATH.

**Tech Stack:** Pinned clang-cl/lld-link, GN/Ninja, Python, CMake, Windows SDK.

**Spec:** User explicitly authorized the previously described actual DLL build, import-library linking, runtime deployment and sample execution; existing `docs/toolchain-design.md` and static SDK plan apply.

## Constraints and review focus

- Windows x64 / Chromium LLVM / Release first; preserve original static SDK and sample behavior.
- No upstream source patches, full checkout, ABI mixing, or maintained per-version DLL list.
- Shared libraries use their own generated headers, component defines and CRT; never reuse static headers/configuration.
- Confirm DLL imports rather than accidentally linking the static SDK.
- Use GN runtime dependencies; preserve transitive dependencies and reject escaping/unsupported paths.
- No reliance on original build directories at runtime; package paths remain relocatable.
- Existing workspace already has working SDK and sample changes; reuse it and preserve those changes.

## Tasks

- [x] Build existing managed shared configuration with six jobs, retaining source/tool identity checks and build-state transitions.
- [x] Add failing tests for shared selection, CRT mismatch and runtime path/deployment handling.
- [x] Extend `scripts/sdk_metadata.py`, `scripts/export_sdk.py` and CMake templates for static/shared Release SDKs using discovered contracts.
- [x] Export and relocate shared SDK; build `samples/hello_base` and SDK verification fixture against it.
- [x] Inspect PE imports, deploy runtime DLLs and run in a clean directory with sanitized PATH; validate sample output and negative missing-DLL behavior.
- [x] Run Python regression tests and static consumer check, obtain independent review, document exact results/limitations.

## Ledger

- Starting branch `feat/dual-clang-toolchains`, HEAD `e946b03`; existing uncommitted `samples/` and README changes are prior user-authorized work.
- Native shared output: `vendor/chromium/out/chromium-base/windows-x64-chromium-shared-release`. Previously configured, not built.
- Build runs via existing driver validation/state handling, with a local logging wrapper passing `-j6`; detailed log `.cache/shared/build.log`.
- Ruling: add optional `--output-dir` beneath `<source>/out`, preserving existing defaults and manifests. Windows native diagnosis proved the same existing directory accepts a 208-character file path but fails for the 269-character Rust temporary path. Use `vendor/chromium/out/sh`; preserve the failed longer output. This avoids upstream patches and OS-wide registry changes.
- Actual shared consumer probe includes 19 runtime DLLs plus optional PDBs; local import libraries are bare filenames. Match them against GN project outputs instead of treating all bare `.lib` names as system libraries. PDBs are excluded explicitly. Both findings have regressions.
- Independent review found no material implementation defects; SDK tests 21/21 and driver tests 27/27 passed independently. Required native execution and static regression subsequently passed.
- Native shared build completed all 2,275 jobs, ending with `LINK(DLL) base.dll base.dll.lib base.dll.pdb`, exit 0. Managed output state is `built`.
- Exported and relocated SDK: `out/sdk/relocated sdk/windows-x64-chromium-shared-release`, 11 link inputs, 19 runtime DLLs, 9,469 files, 127,028,061 bytes. Source integrity and managed tool identity checks passed; no upstream source patches.
- External fixture and `samples/hello_base` compiled, linked and ran. Fixture recorded 2,307 header dependencies with no original source/build references; sample JSON assertions passed for ASCII, Korean and quoted arguments.
- Both isolated deployments passed with PATH restricted to Windows/System32. PE imports include `base.dll`; copied DLL hashes match SDK records; removing base.dll produces `0xC0000135`, then the DLL is restored. Evidence: `out/shared-deployment/{hello_base,sdk_consumer}/runtime-verification.json`.
- Static regression used a copy of the original SDK with current CMake package generation, preserving the original SDK. Compile/link/run passed and 2,315 header dependencies were audited. This copy is a test artifact, not a newly exported SDK.
- Full Python suite: 59 tests passed. Logs: `.cache/shared/{build,export,fixture,sample-build,static-regression,unit-tests}.log`; aggregate result `.cache/shared/verification.json`.
- Verified scope: Windows x64, pinned Chromium LLVM, Release, static/shared. External LLVM, Debug and macOS/Linux native builds remain unverified.
