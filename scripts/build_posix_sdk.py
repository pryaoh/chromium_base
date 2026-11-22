"""Build the pinned Chromium base on a native Linux x64 or macOS arm64 host."""
import argparse
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


def configure(host, linkage, build):
    probe = SOURCE / "out/sdk_probe"
    probe.mkdir(parents=True, exist_ok=True)
    (probe / "probe.cc").write_text("int main() { return 0; }\n")
    (probe / "BUILD.gn").write_text(
        'executable("sdk_probe") {\n  sources = [ "probe.cc" ]\n  deps = [ "//base" ]\n'
        '  write_runtime_deps = "$root_out_dir/sdk_probe.runtime_deps"\n'
        '  data_deps = [ "//third_party/perfetto/src/trace_processor/tables:tables_python" ]\n}\n')
    label = "//out/sdk_probe:sdk_probe"
    component = "true" if linkage == "shared" else "false"
    args = ["is_debug=false", f"is_component_build={component}", "symbol_level=0",
            "use_remoteexec=false", "use_clang_modules=false"]
    if host == "Linux":
        args += ["use_sysroot=false", "use_mold=false", "use_glib=false", "use_udev=false",
                 "icu_use_data_file=false"]
    else:
        # The Apple toolchain also passes -fmodule-name when compiling a C++ PCH.
        # The pinned Clang treats that header as a module interface.
        args += ["use_system_xcode=true", "enable_precompiled_headers=false"]
    run(WORK / "gn", "gen", build, "--args=" + " ".join(args), "--ide=json",
        "--root-target=" + label, "--root-pattern=" + label, "--fail-on-unused-args")
    # Some consumers in this revision lack ordering edges to generated
    # Perfetto and Rust bridge headers. Generate the headers in the GN graph
    # before compiling consumers. Bound argv size on both native hosts.
    entries = output("ninja", "-t", "targets", "all", cwd=build).splitlines()
    headers = [line.rsplit(": ", 1)[0] for line in entries]
    headers = [name for name in headers if name.startswith("gen/") and is_header(name)]
    for start in range(0, len(headers), 100):
        run("ninja", "-j", "4", "-C", build, *headers[start:start + 100])
    run("ninja", "-d", "keeprsp", "-j", "4", "-C", build, "sdk_probe")
    return json.loads((build / "project.json").read_text())["targets"][label]


def package_headers(sdk, linkage, build):
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
    for path in (build / "gen").rglob("*"):
        if path.is_file() and is_header(path.name):
            dest = sdk / "include/generated" / path.relative_to(build / "gen")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
    (sdk / "source.lock.json").write_text(json.dumps(inventory["lock"], indent=2) + "\n")
    manifest = {
        "revision": inventory["revision"],
        "platform": platform.system(),
        "architecture": platform.machine(),
        "linkage": linkage,
        "configuration": "release",
        "compiler": output(LLVM / "clang++", "--version").splitlines()[0],
        "gn_args": (build / "args.gn").read_text(),
    }
    (sdk / "sdk-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for root in (LLVM.parent, SOURCE / "third_party/rust-toolchain"):
        for path in root.rglob("*"):
            if path.is_file() and path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
                dest = sdk / "licenses" / root.name / path.relative_to(root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)


def mac_archive_input(path, scratch, index):
    with path.open("rb") as stream:
        header = stream.read(16)

    # A universal binary can contain either archives or individual objects.
    if header[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf",
                      b"\xbe\xba\xfe\xca", b"\xbf\xba\xfe\xca"):
        sliced = scratch / f"{index}-{path.name}"
        subprocess.run(["xcrun", "lipo", path, "-thin", "arm64", "-output", sliced], check=True)
        with sliced.open("rb") as stream:
            header = stream.read(16)
    else:
        sliced = path

    if header.startswith((b"!<arch>\n", b"!<thin>\n")):
        return "addlib", sliced
    # MH_MAGIC_64 with filetype MH_OBJECT, or raw/wrapped LLVM bitcode.
    if ((header[:4] == b"\xcf\xfa\xed\xfe" and header[12:16] == b"\x01\0\0\0")
            or header.startswith((b"BC\xc0\xde", b"\xde\xc0\x17\x0b"))):
        return "addmod", sliced
    raise ValueError(f"Unsupported macOS static link input: {path} (header: {header.hex()})")


def merge_library(inputs, lib, name="libchromium_base.a"):
    with tempfile.TemporaryDirectory(dir=lib) as temporary:
        mri = [f"create {name}"]
        for index, path in enumerate(inputs):
            if platform.system() == "Darwin":
                command, source = mac_archive_input(path, Path(temporary), index)
            else:
                command, source = ("addmod" if path.suffix == ".o" else "addlib"), path
            mri.append(f'{command} "{source}"')
        result = subprocess.run([LLVM / "llvm-ar", "-M"], cwd=lib,
                                input="\n".join([*mri, "save", "end", ""]),
                                text=True, stderr=subprocess.PIPE)
        if result.returncode:
            match = re.search(r"script line (\d+)", result.stderr)
            line = int(match[1]) if match else 0
            context = f" while processing {inputs[line - 2]}" if 2 <= line <= len(mri) else ""
            raise RuntimeError(f"llvm-ar failed{context}: {result.stderr.strip()}")


def copy_component_libraries(build, lib, suffix):
    # GN includes transitive runtime components that the probe does not link directly.
    names = set()
    for entry in (build / "sdk_probe.runtime_deps").read_text().splitlines():
        path = build / entry
        if path.suffix == suffix:
            if path.name in names:
                raise ValueError(f"Conflicting runtime library name: {path.name}")
            shutil.copy2(path, lib / path.name)
            names.add(path.name)
    if "libbase" + suffix not in names:
        raise ValueError("Missing Chromium base shared library in GN runtime dependencies")
    return names


def package_library(target, sdk, linkage, build):
    # Use the actual executable link inputs, including Rust archives and source_sets.
    entries = json.loads(output("ninja", "-t", "compdb", "link", cwd=build))
    entry = next(item for item in entries if Path(item["output"]).name == "sdk_probe")
    tokens = []
    for arg in shlex.split(entry["command"]):
        if arg.startswith("@"):
            tokens.extend(shlex.split((build / arg[1:]).read_text()))
        else:
            tokens.append(arg)
    lib = sdk / "lib"
    lib.mkdir(parents=True)
    prefix = '${_chromium_base_root}'
    suffix = ".dylib" if platform.system() == "Darwin" else ".so"
    location = "libbase" + suffix if linkage == "shared" else "libchromium_base.a"
    components = copy_component_libraries(build, lib, suffix) if linkage == "shared" else set()
    inputs = []
    link_libraries = []
    for i, token in enumerate(tokens):
        path = build / token
        if token.endswith((".o", ".a", ".rlib")) and path.is_file():
            if path.resolve() != (build / entry["file"]).resolve():
                inputs.append(path.resolve())
        elif path.name in components and path.name != location:
            link_libraries.append(f'"{prefix}/lib/{path.name}"')
        elif token.startswith("-l") and re.fullmatch(r"-l[\w+.-]+", token):
            link_libraries.append(cmake_quote(token))
        elif token in ("-framework", "-weak_framework"):
            link_libraries.append(cmake_quote(token + " " + tokens[i + 1]))
    if linkage == "static":
        if len(inputs) < 2:
            raise ValueError("Missing base link inputs in Ninja compilation database")
        merge_library(inputs, lib)
    elif inputs:
        # Preserve non-component link inputs such as the pinned compiler builtins.
        support = "libchromium_base_support.a"
        merge_library(inputs, lib, support)
        link_libraries.append(f'"{prefix}/lib/{support}"')

    includes = []
    for directory in target["include_dirs"]:
        if not directory.startswith("//"):
            raise ValueError(f"Unexpected non-source include directory: {directory}")
        path = SOURCE / directory[2:]
        if path.is_relative_to(build / "gen"):
            rel = "generated/" + path.relative_to(build / "gen").as_posix()
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
add_library(ChromiumBase::base {linkage.upper()} IMPORTED GLOBAL)
set_target_properties(ChromiumBase::base PROPERTIES IMPORTED_LOCATION "{prefix}/lib/{location}")
target_include_directories(ChromiumBase::base INTERFACE {' '.join(includes)})
target_compile_definitions(ChromiumBase::base INTERFACE {defines})
target_compile_options(ChromiumBase::base INTERFACE {' '.join(flags)})
target_link_options(ChromiumBase::base INTERFACE {link_options})
target_link_libraries(ChromiumBase::base INTERFACE {' '.join(dict.fromkeys(link_libraries))})
""")


def export(target, sdk, linkage, build):
    with tempfile.TemporaryDirectory(dir=sdk.parent) as temporary:
        stage = Path(temporary) / "sdk"
        package_headers(stage, linkage, build)
        package_library(target, stage, linkage, build)
        stage.rename(sdk)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linkage", choices=["static", "shared"], default="static")
    args = parser.parse_args()
    host = platform.system()
    if (host, platform.machine()) not in {("Linux", "x86_64"), ("Darwin", "arm64")}:
        raise SystemExit("Requires native Linux x64 or macOS arm64")
    sdk = ROOT / "out" / f"{args.linkage}-sdk"
    if sdk.exists():
        raise SystemExit(f"SDK destination already exists: {sdk}")
    WORK.mkdir(exist_ok=True, parents=True)
    synchronize(source_lock(host), SOURCE, ROOT / ".cache/standalone", ROOT / "standalone")
    install_tools(host)
    build = SOURCE / "out" / ("sdk-shared" if args.linkage == "shared" else "sdk")
    target = configure(host, args.linkage, build)
    export(target, sdk, args.linkage, build)


if __name__ == "__main__":
    main()
