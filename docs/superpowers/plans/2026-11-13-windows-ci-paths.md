# Windows CI path correction plan

> Execute inline with systematic debugging and test-driven development. The user authorized feature-branch commit/push, green CI, then main merge/push.

**Goal:** Pass the existing Windows/Linux Python matrix without changing SDK contracts or bypassing path containment checks.

**Cause:** Inventory traversal resolves its root but inventory writing does not. Windows temporary paths can use 8.3 aliases. One relative-toolchain test places the compiler in the checkout and the output in a temporary directory on another drive.

**Files:** `scripts/sync_source.py`, `tests/test_sync_source.py`, `tests/test_chromium_base.py`, `tests/test_export_sdk.py`.

## Tasks

- [x] Reproduce inventory failure with a relative root and, where available, a Windows short path; assert real inventory creation and verification. Both fail with the original `relative_to` error on this Windows host.
- [x] Resolve the inventory root once before traversal and serialization. Keep filesystem-link and containment validation intact.
- [x] Normalize test expectations for resolved paths; place the relative-toolchain fixture's repository and output on the same drive.
- [x] Run the complete Python suite and review the change independently. Python 3.11 on Windows: 61 tests passed, including the real short-path regression without skipping. Independent review found an incorrect test assertion against the verifier's return shape; corrected it and reran the green suite. No remaining findings.

## Integration gate

Commit/push the feature branch, wait for all four CI jobs, then fast-forward main and push it. Verify main CI and remote state. The user authorized this sequence; do not merge while any job fails.

Native SDK builds are unchanged and were already verified in the preceding plans; this correction is verified through the Python suite and CI matrix.

## Review focus

- Relative and short paths must yield relative inventory keys and valid hashes.
- Unexpected files, traversal and filesystem links must still be rejected.
- Relative-toolchain coverage must remain meaningful on C:/D: CI layouts.
- Existing static/shared SDK metadata and build commands must remain unchanged.
- No generated SDK, tool or cache files enter the commit.
