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
- [x] External LLVM Release builds and SDK consumers passed on this host on 2026-11-19 at repository commit `9a4e0c9`. The [upstream Windows x64 artifact](https://github.com/llvm/llvm-project/actions/runs/37080272399) (ID `11260327024`) matched SHA-256 `a889ab2ddb4b74d07cdb9b5d099c8c2cf89a2448274640c35500100db8bbf349`. The installed clang-cl reported `24.0.0git` at LLVM commit `6dc0e52d1e7f7ebef472d00b7e4b1e8c8cba146f`.
  - Static completed all 2,346 Ninja actions and exported 579 link inputs. The relocated SDK consumer used 2,315 header dependencies. Both the consumer and `hello_base` ran from separate executable-only folders with a system-only PATH.
  - Shared completed all 2,275 Ninja actions and exported 11 link inputs and 19 DLLs. The relocated consumer used 2,307 header dependencies. Both executables ran with the deployed DLLs and returned `0xC0000135` when `base.dll` was removed.
  - Both consumer audits found zero original source/build path references. Both samples produced the expected JSON for default, ASCII and quoted Korean inputs. Local reports are in `out/sdk-consumer-external-{static,shared}/verification.json` and `out/external-deployment/shared/{hello_base,sdk_consumer}/runtime-verification.json`.

## Integration gate

Commit/push the feature branch, wait for all four CI jobs, then fast-forward main and push. Do not merge while any job fails.
