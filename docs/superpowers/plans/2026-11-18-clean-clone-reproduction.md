# Clean-clone reproduction plan

> Execute inline. The user authorized feature-branch commit/push, green CI, then main merge/push.

**Goal:** Follow the README from a fresh clone on a second Windows host and fix every gap that prevents the documented Chromium LLVM static/shared flow from completing.

**Host:** Windows 11 Pro 10.0.26300 (Korean locale), VS 2026 Community (MSVC 14.51.36231), Python 3.15.2, CMake 4.3.1-msvc1 bundled with VS. Initially only Windows SDK 10.0.26100.0, no SDK debugging tools, no C++ ATL.

## Findings

1. **SDK version not checked by `doctor`.** With `DEPOT_TOOLS_WIN_TOOLCHAIN=0`, upstream `setup_toolchain.py` passes its exact `SDK_VERSION` to `vcvarsall.bat`; `doctor` passed and `configure` failed inside GN. `doctor` now reads that pin and requires the exact version.
2. **SDK "Debugging Tools for Windows" missing.** GN's `copy_dlls` requires `Debuggers/x64/dbghelp.dll`. `doctor` now checks it; README lists it.
3. **Python 3.15 UTF-8 mode (PEP 686).** `build/win/set_appcontainer_acls.py` decodes `icacls` output with the locale code page; on Korean Windows (CP949) the build failed with `UnicodeDecodeError`. The driver and SDK export now run upstream scripts with `PYTHONUTF8=0`, matching Chromium's own Python.
4. **Visual Studio C++ ATL missing.** `base/win/atl_throw.h` includes `atldef.h`. `doctor` checks ATL headers for the default MSVC toolset; README lists the component. Reconfigure after installing it: GN captures include paths at generation time.
5. **`verify_sdk.py` relative tool paths.** The README form `--ninja .tools/ninja/ninja.exe` failed at `ninja -t deps` because `CreateProcess` does not search relative paths. Tool paths are now resolved once.

## Results

- [x] `sync_tools.py` and `sync_source.py --verify`: 34,706 files, unchanged inventory.
- [x] Chromium LLVM static: 847 GN targets, `base.lib`; SDK export 579 link inputs; relocated consumer 2,315 header dependencies with no original-path references; `hello_base` documented commands produce documented output.
- [x] Chromium LLVM shared: 856 GN targets, 2,275 actions; SDK 11 link inputs and 19 DLLs; relocated consumer 2,307 header dependencies; `hello_base` and consumer pass isolated DLL deployment and the missing-`base.dll` `0xC0000135` check.
- [x] Python suite: 67 tests pass (6 new).
- [ ] External LLVM was not re-run on this host; it depends on a GitHub Actions artifact download.

## Integration gate

Commit/push the feature branch, wait for all four CI jobs, then fast-forward main and push. Do not merge while any job fails.
