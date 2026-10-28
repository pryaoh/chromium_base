#!/usr/bin/env python3
"""Build a shared standalone Chromium base snapshot with either LLVM toolchain."""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
import tempfile
from sync_source import INVENTORY, verify_snapshot
from sync_tools import verify_installation


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ".chromium-base.json"


def gn_string(value):
    if any(ord(char) < 32 for char in value):
        raise ValueError("Paths must not contain control characters")
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$') + '"'


def make_plan(source, toolchain="external", llvm_root=None,
              linkage="static", configuration="release"):
    if toolchain not in ("external", "chromium"):
        raise ValueError("Unknown toolchain")
    if linkage not in ("static", "shared") or configuration not in ("release", "debug"):
        raise ValueError("Unknown linkage or configuration")
    source = Path(source).resolve()
    if toolchain == "chromium":
        if llvm_root is not None:
            raise ValueError("--llvm-root is only valid with --toolchain external")
        llvm = REPO_ROOT / ".tools/chromium-llvm"
    else:
        llvm = Path(llvm_root or os.environ.get("LLVM_ROOT") or
                    Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "LLVM").resolve()
    name = f"windows-x64-{toolchain}-{linkage}-{configuration}"
    output = source / "out" / "chromium-base" / name
    rust_root = REPO_ROOT / ".tools/rust-toolchain"
    rust_package = json.loads((REPO_ROOT / "tools.lock.json").read_text())["packages"]["rust-toolchain"]
    args = [
        'target_cpu = "x64"',
        "is_clang = true",
        "use_lld = true",
        "use_remoteexec = false",
        "use_custom_libcxx = true",
        "is_debug = " + str(configuration == "debug").lower(),
        "is_component_build = " + str(linkage == "shared").lower(),
        "clang_base_path = " + gn_string(llvm.as_posix()),
        "rust_sysroot_absolute = " + gn_string(rust_root.as_posix()),
        "rust_bindgen_root = " + gn_string(rust_root.as_posix()),
        "rust_crubit_root = " + gn_string(rust_root.as_posix()),
        "rustc_version = " + gn_string(rust_package["sha256"]),
    ]
    if toolchain == "external":
        args += ["clang_use_chrome_plugins = false"]
    return {
        "source": str(source), "toolchain": toolchain, "llvm_root": str(llvm),
        "linkage": linkage, "configuration": configuration,
        "output": str(output), "gn_args": "\n".join(args) + "\n",
    }


def capture(command, cwd=None):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30, check=True)
    return result.stdout.strip()


def windows_prerequisites():
    """Return host locations and errors; GN remains responsible for SDK version floors."""
    info, errors = {}, []
    if platform.system() != "Windows":
        return info, ["Native builds currently require Windows; plan works on any host"]
    program_files = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    vswhere = program_files / "Microsoft Visual Studio/Installer/vswhere.exe"
    try:
        vs = capture([str(vswhere), "-latest", "-products", "*", "-requires",
                      "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                      "-property", "installationPath"])
        if not vs or not (Path(vs) / "VC/Auxiliary/Build/vcvars64.bat").is_file():
            errors.append("Install Visual Studio Desktop development with C++ (x64 tools)")
        else:
            info["visual_studio"] = vs
    except (OSError, subprocess.SubprocessError) as error:
        errors.append(f"Cannot detect Visual Studio C++ tools: {error}")
    sdk = Path(os.environ.get("WindowsSdkDir") or program_files / "Windows Kits/10")
    versions = []
    if (sdk / "Include").is_dir():
        for include in (sdk / "Include").iterdir():
            if all(path.is_file() for path in (
                include / "um/Windows.h", include / "ucrt/stdio.h",
                sdk / "Lib" / include.name / "um/x64/kernel32.lib",
                sdk / "Lib" / include.name / "ucrt/x64/ucrt.lib",
                sdk / "bin" / include.name / "x64/rc.exe",
            )):
                versions.append(include.name)
    if not versions:
        errors.append("Windows SDK with x64 headers, libraries and rc.exe is missing")
    info["windows_sdk_root"] = str(sdk)
    info["windows_sdk_versions"] = sorted(versions)
    return info, errors


def inspect_environment(plan, depot_tools=None, gn=None, ninja=None):
    source, llvm = Path(plan["source"]), Path(plan["llvm_root"])
    errors, warnings = [], []
    for label, path in (("Chromium source", source), ("LLVM", llvm)):
        if re.search(r'[\s&|<>^%!"$();]', str(path)):
            errors.append(f"{label} path contains whitespace or shell metacharacters; upstream Windows rules require a simple path such as C:/src or C:/LLVM: {path}")
    identity, host_errors = windows_prerequisites()
    errors.extend(host_errors)
    try:
        identity["rust_toolchain"] = inspect_rust()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        errors.append(f"Rust toolchain: {error}")
    required = (".gn", "DEPS", "base/BUILD.gn", "build/config/BUILDCONFIG.gn")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        errors.append("Chromium source snapshot missing: " + ", ".join(missing))
    elif (source / INVENTORY).is_file():
        try:
            identity.update(verify_snapshot(source))
        except (OSError, ValueError, KeyError) as error:
            errors.append(f"Invalid source snapshot: {error}")
    else:
        try:
            top = Path(capture(["git", "rev-parse", "--show-toplevel"], cwd=source)).resolve()
            if top != source:
                raise ValueError("--source must be the root of Chromium's own Git checkout")
            identity["revision"] = capture(["git", "rev-parse", "HEAD"], cwd=source)
            if capture(["git", "status", "--porcelain", "--untracked-files=no"], cwd=source):
                errors.append("Chromium has tracked local changes; commit or restore them before configuring")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(f"Cannot identify Chromium revision: {error}")
    versions, majors = {}, {}
    # Upstream Windows GN uses lld-link /lib as its librarian, not llvm-lib.
    for tool in ("clang-cl", "lld-link"):
        executable = llvm / "bin" / (tool + ".exe")
        if not executable.is_file():
            errors.append(f"Selected {plan['toolchain']} tool missing: {executable}")
            continue
        try:
            version = capture([str(executable), "--version"])
            match = re.search(r"(?:clang version|LLVM version|LLD)\s+(\d+)", version)
            if not match:
                errors.append(f"Cannot determine LLVM version for {executable}")
            else:
                majors[tool] = int(match.group(1))
            versions[tool] = version
        except (OSError, subprocess.SubprocessError) as error:
            errors.append(f"Cannot execute {executable}: {error}")
    if len(set(majors.values())) > 1:
        errors.append("Selected LLVM tools have mismatched major versions")
    identity["compiler_versions"] = versions
    toolchain_gni = source / "build/toolchain/toolchain.gni"
    if toolchain_gni.is_file() and "clang-cl" in majors:
        declarations = re.findall(r'^\s*clang_version\s*=\s*([^\r\n]*)',
                                  toolchain_gni.read_text(encoding="utf-8"), re.MULTILINE)
        match = re.fullmatch(r'"(\d+)"\s*(?:#.*)?', declarations[0]) if len(declarations) == 1 else None
        if match and int(match.group(1)) != majors["clang-cl"]:
            errors.append(f"Checkout expects Clang major {match.group(1)}, selected LLVM is {majors['clang-cl']}; select a compatible checkout/toolchain")
        elif not match:
            warnings.append("Checkout clang_version is conditional or dynamic; defer version compatibility to GN")
    if plan["toolchain"] == "external":
        warnings.append("Matching LLVM major versions is necessary here but does not prove compatibility with Chromium/libc++")
    gn_path = Path(gn).resolve() if gn else REPO_ROOT / ".tools/gn/gn.exe"
    if not gn_path.is_file():
        errors.append(f"GN missing: {gn_path}; prepare the pinned tools or pass --gn")
    else:
        try:
            identity["gn_version"] = capture([str(gn_path), "--version"])
        except (OSError, subprocess.SubprocessError) as error:
            errors.append(f"Cannot execute GN: {error}")
    depot = depot_tools or os.environ.get("DEPOT_TOOLS")
    depot = Path(depot).resolve() if depot else None
    ninja_path = Path(ninja).resolve() if ninja else REPO_ROOT / ".tools/ninja/ninja.exe"
    if depot is not None and ninja is None:
        if not (depot / "autoninja.py").is_file():
            errors.append("depot_tools/autoninja.py missing; pass --ninja or a valid --depot-tools")
        ninja_path = None
    elif not ninja_path.is_file():
        errors.append(f"Ninja missing: {ninja_path}; prepare the pinned tools or pass --ninja")
    else:
        try:
            identity["ninja_version"] = capture([str(ninja_path), "--version"])
        except (OSError, subprocess.SubprocessError) as error:
            errors.append(f"Cannot execute Ninja: {error}")
    identity["gn_path"] = str(gn_path)
    identity["depot_tools"] = str(depot) if depot else None
    identity["ninja_path"] = str(ninja_path) if ninja_path else None
    warnings.append("GN checks exact SDK and dependency requirements; doctor does not prove dependency closure")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "gn": str(gn_path), "depot_tools": str(depot) if depot else None,
            "ninja": str(ninja_path) if ninja_path else None,
            "identity": identity}


def run_command(command, *, cwd, env):
    return subprocess.run(command, cwd=cwd, env=env, check=False).returncode


def inspect_rust():
    root = REPO_ROOT / ".tools/rust-toolchain"
    package = json.loads((REPO_ROOT / "tools.lock.json").read_text())["packages"]["rust-toolchain"]
    identity = verify_installation(root, package)
    executable = root / "bin/rustc.exe"
    if not executable.is_file():
        raise ValueError(f"Missing Rust compiler: {executable}")
    identity["rustc_version"] = capture([str(executable), "--version"])
    return identity


def build_environment(report):
    env = dict(os.environ)
    env["DEPOT_TOOLS_WIN_TOOLCHAIN"] = "0"
    env["DEPOT_TOOLS_UPDATE"] = "0"
    env["CHROMIUM_BASE_PYTHON"] = sys.executable
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if report.get("depot_tools"):
        env["PATH"] = str(report["depot_tools"]) + os.pathsep + env.get("PATH", "")
    return env


def checked_output(plan):
    source = Path(plan["source"]).resolve()
    output = Path(plan["output"])
    if not output.resolve().is_relative_to(source):
        raise ValueError("Output resolves outside the Chromium checkout")
    for name in (MANIFEST, "args.gn"):
        if (output / name).is_symlink():
            raise ValueError(f"Refusing linked output file: {name}")
    return output


def read_manifest(plan, report, *, allow_new=False):
    if not report["ok"]:
        raise ValueError("Prerequisites failed: " + "; ".join(report["errors"]))
    output = checked_output(plan)
    path = output / MANIFEST
    if not path.exists():
        if allow_new and (not output.exists() or not any(output.iterdir())):
            return None
        raise ValueError("Output is unmanaged or not configured; use a fresh output directory")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("plan") != plan:
        raise ValueError("Output configuration differs; preserve it and use a fresh output directory")
    if manifest.get("identity") != report["identity"]:
        raise ValueError("Source/toolchain identity changed; preserve this output and configure a fresh output directory")
    args = output / "args.gn"
    if not args.is_file() or args.read_text(encoding="utf-8") != plan["gn_args"]:
        raise ValueError("args.gn was modified or removed; refusing to overwrite it")
    return manifest


def write_manifest(plan, report, state):
    output = checked_output(plan)
    content = {"schema": 1, "plan": plan, "identity": report["identity"], "state": state}
    # Replace atomically so an interrupted write cannot look like a completed build.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output,
                                     prefix=".manifest-", suffix=".tmp", delete=False) as stream:
        json.dump(content, stream, indent=2)
        temporary = Path(stream.name)
    try:
        temporary.replace(output / MANIFEST)
    finally:
        temporary.unlink(missing_ok=True)


def verify_generated_toolchain(plan):
    output = checked_output(plan)
    rules = output / "toolchain.ninja"
    if not (output / "build.ninja").is_file() or not rules.is_file():
        raise ValueError("GN did not produce build.ninja and toolchain.ninja")
    text = rules.read_text(encoding="utf-8").replace("$\n", "").replace("\\", "/").replace("$:", ":").replace("$ ", " ")
    root = Path(plan["llvm_root"]) / "bin"
    tools = ("clang-cl.exe", "lld-link.exe")
    referenced = set()
    for line in text.splitlines():
        command = re.match(r"\s*command\s*=\s*(.*)", line)
        if not command or not any(tool in line.casefold() for tool in tools):
            continue
        try:
            tokens = shlex.split(command.group(1))
        except ValueError as error:
            raise ValueError(f"Cannot parse compiler command in toolchain.ninja: {error}") from error
        for token in tokens:
            candidate = Path(token)
            if candidate.name.casefold() not in tools:
                continue
            if not candidate.is_absolute():
                candidate = output / candidate
            referenced.add(str(candidate.resolve()).casefold())
    for tool in tools:
        if str((root / tool).resolve()).casefold() not in referenced:
            raise ValueError(f"toolchain.ninja does not reference selected {tool}; check generated commands")


def configure(plan, report):
    read_manifest(plan, report, allow_new=True)
    output = checked_output(plan)
    output.mkdir(parents=True, exist_ok=True)
    (output / "args.gn").write_text(plan["gn_args"], encoding="utf-8")
    write_manifest(plan, report, "configuring")
    command = [report["gn"], "gen", str(output), "--fail-on-unused-args"]
    try:
        result = run_command(command, cwd=plan["source"], env=build_environment(report))
        if result:
            raise subprocess.CalledProcessError(result, command)
        verify_generated_toolchain(plan)
    except (OSError, ValueError, subprocess.SubprocessError):
        write_manifest(plan, report, "configure_failed")
        raise
    write_manifest(plan, report, "configured")


def build(plan, report):
    manifest = read_manifest(plan, report)
    if manifest["state"] not in ("configured", "built", "build_failed"):
        raise ValueError("Run configure successfully before build")
    verify_generated_toolchain(plan)
    command = ([report["ninja"]] if report.get("ninja") else
               [sys.executable, str(Path(report["depot_tools"]) / "autoninja.py")])
    command += ["-C", plan["output"], "base"]
    write_manifest(plan, report, "building")
    try:
        result = run_command(command, cwd=plan["source"], env=build_environment(report))
        if result:
            raise subprocess.CalledProcessError(result, command)
    except (OSError, ValueError, subprocess.SubprocessError):
        write_manifest(plan, report, "build_failed")
        raise
    write_manifest(plan, report, "built")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "doctor", "configure", "build"))
    parser.add_argument("--source", type=Path, default=REPO_ROOT / "vendor/chromium",
                        help="Shared source snapshot produced by sync_source.py")
    parser.add_argument("--toolchain", choices=("external", "chromium"), default="external")
    parser.add_argument("--llvm-root", type=Path, help="External LLVM root; otherwise LLVM_ROOT or Program Files/LLVM")
    parser.add_argument("--linkage", choices=("static", "shared"), default="static")
    parser.add_argument("--configuration", choices=("release", "debug"), default="release")
    parser.add_argument("--depot-tools", type=Path, help="depot_tools directory containing autoninja.py")
    parser.add_argument("--gn", type=Path, help="Override .tools/gn/gn.exe")
    parser.add_argument("--ninja", type=Path, help="Override .tools/ninja/ninja.exe; no depot_tools required")
    args = parser.parse_args(argv)
    try:
        plan = make_plan(args.source, args.toolchain, args.llvm_root, args.linkage, args.configuration)
        if args.command == "plan":
            print(json.dumps(plan, indent=2))
            return 0
        report = inspect_environment(plan, args.depot_tools, args.gn, args.ninja)
        if args.command == "doctor":
            print(json.dumps(dict(plan=plan, **report), indent=2))
            return 0 if report["ok"] else 1
        for warning in report["warnings"]:
            print(f"warning: {warning}", file=sys.stderr)
        if args.command == "configure":
            configure(plan, report)
        else:
            build(plan, report)
        print(f"{args.command} succeeded: {plan['output']}")
        return 0
    except subprocess.CalledProcessError as error:
        print(f"error: command failed with exit code {error.returncode}: {error.cmd}", file=sys.stderr)
        return error.returncode if 0 < error.returncode < 256 else 1
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
