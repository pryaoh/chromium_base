# External LLVM verification plan

> **For agentic workers:** Use superpowers:executing-plans inline for the existing build and SDK verification workflow.

**Goal:** Verify Windows x64 Release static/shared builds and consumers with an independently distributed LLVM compiler.

**Architecture:** Reuse the pinned selected Chromium source and common GN/Ninja/Rust tools. Obtain an official upstream LLVM 24 Windows binary, record provenance and hashes, and use separate short output directories and SDK destinations. Preserve existing Chromium LLVM results.

**Tech Stack:** LLVM clang-cl/lld-link, GN/Ninja, Python, CMake, installed Visual Studio and Windows SDK.

**Spec:** User request to verify external LLVM, following completed Chromium LLVM static/shared verification and `docs/toolchain-design.md`.

## Constraints

- Same source snapshot; no upstream source patches or version-check bypass.
- External compiler must actually be independently distributed, not the Chromium compiler under another path.
- Do not change system PATH or replace existing SDKs.
- Verify compiler provenance/version before long builds; use six compile jobs and monitor disk availability.
- This verifies the selected compiler build, not all releases with matching major version.

## Tasks

- [x] Locate/install an official upstream Windows LLVM 24 package, record origin and SHA-256. Native compatibility remains to be tested.
- [ ] Run managed environment checks and configure short independent static/shared outputs.
- [ ] Build both modes, export and relocate SDKs.
- [ ] Compile/run external fixture and sample per mode, audit headers and shared runtime deployment.
- [ ] Record exact results, limitations and reproducible commands in repository docs.

## Evidence

- Initial inspection: no clang-cl/lld-link in PATH, default `C:/Program Files/LLVM`, VS LLVM locations, or project tools. LLVM_ROOT unset.
- Pinned source requires Clang major 24. Official latest stable release is 23.1.4; upstream Actions publishes LLVM 24 development packages. Checking availability before installation.
- Initial free disk: approximately 23.6 GiB.
- Installed upstream `24.0.0git`, commit `6dc0e52d1e7f7ebef472d00b7e4b1e8c8cba146f`, from official main run https://github.com/llvm/llvm-project/actions/runs/37080272399 (Windows artifact 11260327024, created 2026-10-03).
- Artifact SHA-256 verified: `a889ab2ddb4b74d07cdb9b5d099c8c2cf89a2448274640c35500100db8bbf349`. Download 1,648,572,324 bytes; expanded tar.xz package 3,923,747,620 bytes. Installed in `.tools/external-llvm`; clang-cl and lld-link version execution passed.
- Ruling: use existing feature workspace and source snapshot for validation; no production behavior change or new checkout required. Generated logs/scripts stay in `.cache/external`, source output directories are `out/eh` (shared) and `out/es` (static).
- Native pipeline `.cache/external/verify.py` preserves managed identity/state validation and uses six Ninja jobs. It exports to new external SDK destinations, relocates, verifies consumers and shared DLL deployment. Status and failures are written to `.cache/external/status.json`.
- Managed environment/source checks passed. Shared GN generation passed and generated-toolchain validation confirmed the selected external clang-cl/lld-link. Native shared compilation is running; libc++ and Abseil compiled without changes, Protobuf is in progress.
- Shared native build completed 2,275/2,275 tasks. Exported SDK was relocated to `out/sdk/relocated sdk/windows-x64-external-shared-release`. Fixture and hello_base passed; 2,307 header dependencies, no original source/build references. Both isolated 19-DLL deployments passed with system-only PATH, PE base.dll import, hash checks and missing-DLL status 0xC0000135. Evidence `.cache/external/verification.json` and `out/external-deployment/*/runtime-verification.json`.
- On 2026-10-30, static log ended at 834/2,346 and no native build processes remained; tool sessions were gone. Resuming with `.cache/external/verify.py --resume-static`, preserving successful shared evidence and existing static objects. Managed identity check and configure re-establish a valid state before Ninja resumes.
- User explicitly requested incremental commits and push. Full Python suite rerun: 59 passed. Final independent code review found no material defects. Group commits by short output paths, shared SDK/runtime support, runnable samples, and verification documentation. No PR or merge requested.
