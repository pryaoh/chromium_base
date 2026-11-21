"""Build the pinned Chromium base on a native Linux x64 or macOS arm64 host."""
import json
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from export_sdk import cmake_quote, is_header
from sync_source import INVENTORY, ROOT, synchronize

WORK = ROOT / "out/native"
SOURCE = WORK / "src"
BUILD = SOURCE / "out/sdk"
SDK = ROOT / "out/static-sdk"
LLVM = SOURCE / "third_party/llvm-build/Release+Asserts/bin"


def run(*args, cwd=SOURCE):
    subprocess.run(args, cwd=cwd, check=True)


def output(*args, cwd=SOURCE):
    return subprocess.check_output(args, cwd=cwd, text=True)


def source_lock(host):
    lock = json.loads((ROOT / "source.lock.json").read_text())
    if host == "Darwin":
        # //base:plist_size_buildflags reads the upstream plist during gn gen.
        lock["repositories"][0]["paths"].append("chrome/app/app-Info.plist")
    elif host == "Linux":
        lock["repositories"].append({
            "name": "lss", "destination": "third_party/lss",
            "url": "https://chromium.googlesource.com/linux-syscall-support.git",
            "revision": "29164a80da4d41134950d76d55199ea33fbb9613",
            "paths": ["linux_syscall_support.h"],
        })
        lock["repositories"].append({
            "name": "icu", "destination": "third_party/icu",
            "url": "https://chromium.googlesource.com/chromium/deps/icu.git",
            "revision": "1add19737289cf93dcebb981ed8f07885c4c26af",
            "paths": ["BUILD.gn", "LICENSE", "README.chromium", "config.gni", "sources.gni",
                      "version.gni", "version.json", "common_src.list", "common_hdr.list",
                      "i18n_src.list", "i18n_hdr.list", "common", "source/common",
                      "source/i18n", "source/stubdata", "scripts"],
        })
    return lock


def install_tools(host):
    deps = (SOURCE / "DEPS").read_text()
    package = "linux-amd64" if host == "Linux" else "mac-arm64"
    revision = re.search(r"'gn_version': '([^']+)'", deps)[1]
    run("curl", "--fail", "--location", "--retry", "3", "--output", WORK / "gn.zip",
        f"https://chrome-infra-packages.appspot.com/dl/gn/gn/{package}/+/{revision}")
    with zipfile.ZipFile(WORK / "gn.zip") as archive:
        archive.extract("gn", WORK)
    (WORK / "gn").chmod(0o755)
    run(sys.executable, "tools/clang/scripts/update.py")
    run(sys.executable, "tools/rust/update_rust.py")


def configure(host):
    probe = SOURCE / "out/sdk_probe"
    probe.mkdir(parents=True, exist_ok=True)
    (probe / "probe.cc").write_text("int main() { return 0; }\n")
    (probe / "BUILD.gn").write_text(
        'executable("sdk_probe") {\n  sources = [ "probe.cc" ]\n  deps = [ "//base" ]\n'
        '  data_deps = [ "//third_party/perfetto/src/trace_processor/tables:tables_python" ]\n}\n')
    label = "//out/sdk_probe:sdk_probe"
    args = ["is_debug=false", "is_component_build=false", "symbol_level=0",
            "use_remoteexec=false", "use_clang_modules=false"]
    if host == "Linux":
        args += ["use_sysroot=false", "use_mold=false", "use_glib=false", "use_udev=false",
                 "icu_use_data_file=false"]
    else:
        # The Apple toolchain also passes -fmodule-name when compiling a C++ PCH.
        # The pinned Clang treats that header as a module interface.
        args += ["use_system_xcode=true", "enable_precompiled_headers=false"]
    run(WORK / "gn", "gen", BUILD, "--args=" + " ".join(args), "--ide=json",
        "--root-target=" + label, "--root-pattern=" + label, "--fail-on-unused-args")
    # Some consumers in this revision lack ordering edges to generated
    # Perfetto and Rust bridge headers. Generate the headers in the GN graph
    # before compiling consumers. Bound argv size on both native hosts.
    entries = output("ninja", "-t", "targets", "all", cwd=BUILD).splitlines()
    headers = [line.rsplit(": ", 1)[0] for line in entries]
    headers = [name for name in headers if name.startswith("gen/") and is_header(name)]
    for start in range(0, len(headers), 100):
        run("ninja", "-j", "4", "-C", BUILD, *headers[start:start + 100])
    run("ninja", "-d", "keeprsp", "-j", "4", "-C", BUILD, "sdk_probe")
    return json.loads((BUILD / "project.json").read_text())["targets"][label]


def package_headers(sdk):
    inventory = json.loads((SOURCE / INVENTORY).read_text())
    for name in inventory["files"]:
        path = SOURCE / name
        if is_header(name):
            dest = sdk / "include/source" / name
        elif path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE", "AUTHORS", "README.CHROMIUM")):
            dest = sdk / "licenses" / name
        else:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    for path in (BUILD / "gen").rglob("*"):
        if path.is_file() and is_header(path.name):
            dest = sdk / "include/generated" / path.relative_to(BUILD / "gen")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
    (sdk / "source.lock.json").write_text(json.dumps(inventory["lock"], indent=2) + "\n")
    manifest = {
        "revision": inventory["revision"],
        "platform": platform.system(),
        "architecture": platform.machine(),
        "linkage": "static",
        "configuration": "release",
        "compiler": output(LLVM / "clang++", "--version").splitlines()[0],
        "gn_args": (BUILD / "args.gn").read_text(),
    }
    (sdk / "sdk-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for root in (LLVM.parent, SOURCE / "third_party/rust-toolchain"):
        for path in root.rglob("*"):
            if path.is_file() and path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
                dest = sdk / "licenses" / root.name / path.relative_to(root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)


def package_library(target, sdk):
    # Use the actual executable link inputs, including Rust archives and source_sets.
    entries = json.loads(output("ninja", "-t", "compdb", "link", cwd=BUILD))
    entry = next(item for item in entries if Path(item["output"]).name == "sdk_probe")
    tokens = []
    for arg in shlex.split(entry["command"]):
        if arg.startswith("@"):
            tokens.extend(shlex.split((BUILD / arg[1:]).read_text()))
        else:
            tokens.append(arg)
    mri = ["create libchromium_base.a"]
    system = []
    for i, token in enumerate(tokens):
        path = BUILD / token
        if token.endswith((".o", ".a", ".rlib")) and path.is_file():
            if path.resolve() != (BUILD / entry["file"]).resolve():
                mri.append(("addmod " if token.endswith(".o") else "addlib ") + f'"{path.resolve()}"')
        elif token.startswith("-l") and re.fullmatch(r"-l[\w+.-]+", token):
            system.append(cmake_quote(token))
        elif token in ("-framework", "-weak_framework"):
            system.append(cmake_quote(token + " " + tokens[i + 1]))
    if len(mri) < 3:
        raise ValueError("Missing base link inputs in Ninja compilation database")
    lib = sdk / "lib"
    lib.mkdir(parents=True)
    ar = LLVM / "llvm-ar"
    subprocess.run([ar, "-M"], cwd=lib, input="\n".join([*mri, "save", "end", ""]),
                   text=True, check=True)

    prefix = '${_chromium_base_root}'
    includes = []
    for directory in target["include_dirs"]:
        if not directory.startswith("//"):
            raise ValueError(f"Unexpected non-source include directory: {directory}")
        path = SOURCE / directory[2:]
        if path.is_relative_to(BUILD / "gen"):
            rel = "generated/" + path.relative_to(BUILD / "gen").as_posix()
        else:
            rel = "source/" + path.relative_to(SOURCE).as_posix()
        dest = sdk / "include" / rel
        if dest.is_dir():
            includes.append(f'"{prefix}/include/{rel}"')
    for name in ("libc++", "libc++abi"):
        includes.append(f'"{prefix}/include/source/third_party/{name}/src/include"')
    defines = " ".join(cmake_quote(d) for d in target["defines"])
    abi_flags = {"-nostdinc++", "-fno-exceptions", "-fno-rtti", "-pthread",
                 "-fexperimental-relative-c++-abi-vtables", "-fsized-deallocation",
                 "-fno-sized-deallocation", "-fvisibility-inlines-hidden"}
    flags = [flag for flag in target["cflags"] + target["cflags_cc"]
             if flag in abi_flags or flag.startswith("-std=")]
    # Chromium archives can contain LLVM bitcode. Use the linker shipped
    # with the same Clang that compiled the SDK.
    link_options = "-nostdlib++ -fuse-ld=lld"
    if platform.system() == "Darwin":
        link_options += " -Wl,-ObjC"
    config = lib / "cmake/ChromiumBase/ChromiumBaseConfig.cmake"
    config.parent.mkdir(parents=True)
    config.write_text(f"""if(TARGET ChromiumBase::base)
  return()
endif()
get_filename_component(_chromium_base_root "${{CMAKE_CURRENT_LIST_DIR}}/../../.." ABSOLUTE)
add_library(ChromiumBase::base STATIC IMPORTED GLOBAL)
set_target_properties(ChromiumBase::base PROPERTIES IMPORTED_LOCATION "{prefix}/lib/libchromium_base.a")
target_include_directories(ChromiumBase::base INTERFACE {' '.join(includes)})
target_compile_definitions(ChromiumBase::base INTERFACE {defines})
target_compile_options(ChromiumBase::base INTERFACE {' '.join(flags)})
target_link_options(ChromiumBase::base INTERFACE {link_options})
target_link_libraries(ChromiumBase::base INTERFACE {' '.join(dict.fromkeys(system))})
""")


def export(target):
    with tempfile.TemporaryDirectory(dir=SDK.parent) as temporary:
        stage = Path(temporary) / "sdk"
        package_headers(stage)
        package_library(target, stage)
        stage.rename(SDK)


def main():
    host = platform.system()
    if (host, platform.machine()) not in {("Linux", "x86_64"), ("Darwin", "arm64")}:
        raise SystemExit("Requires native Linux x64 or macOS arm64")
    if SDK.exists():
        raise SystemExit(f"SDK destination already exists: {SDK}")
    WORK.mkdir(exist_ok=True, parents=True)
    synchronize(source_lock(host), SOURCE, ROOT / ".cache/standalone", ROOT / "standalone")
    install_tools(host)
    target = configure(host)
    export(target)


if __name__ == "__main__":
    main()
