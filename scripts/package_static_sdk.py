"""Package a static SDK and run hello_base against the extracted zip."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=["windows-x64", "linux-x64", "macos-arm64"])
    args = parser.parse_args()
    native = {("Windows", "amd64"): "windows-x64", ("Linux", "x86_64"): "linux-x64",
              ("Darwin", "arm64"): "macos-arm64"}
    if args.platform != native.get((platform.system(), platform.machine().lower())):
        raise SystemExit("Archive platform must match the native build host")
    output = ROOT / "out/release"
    output.mkdir(parents=True, exist_ok=True)
    sdk = ROOT / "out/static-sdk"
    if not (sdk / "lib/cmake/ChromiumBase/ChromiumBaseConfig.cmake").is_file():
        raise SystemExit("Missing exported CMake SDK")
    with tempfile.TemporaryDirectory(dir=output) as temp:
        work = Path(temp)
        archive = work / f"chromium-base-{args.platform}-static.zip"
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
            entries = (ROOT / "vendor/chromium/out/s/environment.x64").read_bytes().decode().split("\0")
            env.update(entry.split("=", 1) for entry in entries if "=" in entry)
        else:
            clang = ROOT / "out/native/src/third_party/llvm-build/Release+Asserts/bin/clang++"
            options.append(f"-DCMAKE_CXX_COMPILER={clang}")
        subprocess.run([cmake, "-S", ROOT / "samples/hello_base", "-B", build,
                        "-G", "Ninja", *options], env=env, check=True)
        subprocess.run([cmake, "--build", build], env=env, check=True)
        result = subprocess.check_output([build / "bin" / executable, "--name=SDK"],
                                         cwd=work, env=env, text=True)
        if json.loads(result) != {"greeting": "Hello, SDK!", "upper_name": "SDK"}:
            raise ValueError(f"Unexpected sample output: {result}")
        archive.replace(output / archive.name)


if __name__ == "__main__":
    main()
