"""Package an SDK and verify hello_base against the extracted zip."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=["windows-x64", "linux-x64", "macos-arm64"])
    parser.add_argument("--linkage", choices=["static", "shared"], default="static")
    args = parser.parse_args()
    native = {("Windows", "amd64"): "windows-x64", ("Linux", "x86_64"): "linux-x64",
              ("Darwin", "arm64"): "macos-arm64"}
    if args.platform != native.get((platform.system(), platform.machine().lower())):
        raise SystemExit("Archive platform must match the native build host")
    output = ROOT / "out/release"
    output.mkdir(parents=True, exist_ok=True)
    sdk = ROOT / "out" / f"{args.linkage}-sdk"
    if not (sdk / "lib/cmake/ChromiumBase/ChromiumBaseConfig.cmake").is_file():
        raise SystemExit("Missing exported CMake SDK")
    with tempfile.TemporaryDirectory(dir=output) as temp:
        work = Path(temp)
        archive = work / f"chromium-base-{args.platform}-{args.linkage}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=4) as package:
            for path in sorted(sdk.rglob("*")):
                if path.is_file():
                    package.write(path, path.relative_to(sdk))
        relocated = work / "relocated sdk"
        with zipfile.ZipFile(archive) as package:
            package.extractall(relocated)
        cmake = shutil.which("cmake")
        env = os.environ.copy()
        build = work / "consumer"
        options = [f"-DCMAKE_PREFIX_PATH={relocated}", "-DCMAKE_BUILD_TYPE=Release"]
        executable = "hello_base"
        if args.platform == "windows-x64":
            executable += ".exe"
            options += [f"-DCMAKE_TOOLCHAIN_FILE={relocated}/lib/cmake/ChromiumBase/chromium-base-toolchain.cmake",
                        f"-DCHROMIUM_BASE_LLVM_ROOT={ROOT}/.tools/chromium-llvm",
                        f"-DCMAKE_MAKE_PROGRAM={ROOT}/.tools/ninja/ninja.exe"]
            build_name = "sh" if args.linkage == "shared" else "s"
            entries = (ROOT / "vendor/chromium/out" / build_name / "environment.x64").read_bytes().decode().split("\0")
            env.update(entry.split("=", 1) for entry in entries if "=" in entry)
        else:
            clang = ROOT / "out/native/src/third_party/llvm-build/Release+Asserts/bin/clang++"
            options.append(f"-DCMAKE_CXX_COMPILER={clang}")
            if args.linkage == "shared":
                # Exercise the consumer's own runtime search paths.
                for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "DYLD_LIBRARY_PATH",
                            "DYLD_FALLBACK_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES"):
                    env.pop(key, None)
        subprocess.run([cmake, "-S", ROOT / "base/samples/hello_base", "-B", build,
                        "-G", "Ninja", *options], env=env, check=True)
        subprocess.run([cmake, "--build", build], env=env, check=True)
        result = subprocess.check_output([build / "bin" / executable, "--name=SDK"],
                                         cwd=work, env=env, text=True)
        if json.loads(result) != {"greeting": "Hello, SDK!", "upper_name": "SDK"}:
            raise ValueError(f"Unexpected sample output: {result}")
        if args.linkage == "shared" and args.platform == "windows-x64":
            dumpbin = shutil.which("dumpbin.exe", path=env["PATH"])
            if not dumpbin:
                raise SystemExit("Missing dumpbin.exe in the Windows build environment")
            subprocess.run([sys.executable, ROOT / "base/tests/verify_dll_runtime.py",
                            "--sdk", relocated, "--executable", build / "bin" / executable,
                            "--deployment", work / "deployment", "--dumpbin", dumpbin],
                           env=env, check=True)
        elif args.linkage == "shared":
            program = build / "bin" / executable
            if args.platform == "macos-arm64":
                deps = subprocess.check_output(["otool", "-L", program], text=True)
                base_dependency = "@rpath/libbase.dylib"
            else:
                deps = subprocess.check_output(["readelf", "-d", program],
                                               env=dict(env, LC_ALL="C"), text=True)
                base_dependency = "Shared library: [libbase.so]"
            if base_dependency not in deps:
                raise ValueError(f"Sample does not dynamically link Chromium base:\n{deps}")
        archive.replace(output / archive.name)


if __name__ == "__main__":
    main()
