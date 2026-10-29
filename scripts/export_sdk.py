#!/usr/bin/env python3
"""Export a built Windows x64 static Release base as a relocatable CMake SDK."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from sdk_metadata import (consumer_flags, expanded_command, link_contract,
                          parse_args, validate_configuration)
from sync_source import INVENTORY, regular_files, sha256, verify_snapshot

ROOT = Path(__file__).resolve().parents[1]
HEADER_SUFFIXES = {'.h', '.hh', '.hpp', '.hxx', '.inc', '.inl', '.ipp', '.tcc', '.def'}


def run(command, cwd=None, env=None):
    result = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {command[0]}\n'
                           + result.stdout[-6000:] + result.stderr[-6000:])
    return result.stdout


def contained(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'Path escapes allowed root: {path}')
    return path


def check_destination(destination, protected):
    destination = Path(destination).resolve()
    for root in protected:
        root = Path(root).resolve()
        if destination.is_relative_to(root) or root.is_relative_to(destination):
            raise ValueError('SDK destination overlaps source/build/tool inputs')
    if destination.exists():
        raise FileExistsError(f'Refusing to replace existing SDK: {destination}')


def is_header(name):
    path = Path(name)
    return (path.suffix.lower() in HEADER_SUFFIXES or
            name.startswith('third_party/libc++/src/include/') or
            name.startswith('buildtools/third_party/libc++/__'))


def cmake_quote(value):
    if any(c in value for c in (';', '$', '\n', '\r')):
        raise ValueError('Unsafe CMake list value: ' + value)
    return '"' + value.replace('\\', '/').replace('"', '\\"') + '"'


def compdb(ninja, build, rule, expanded=False):
    entries = json.loads(run([ninja, '-C', build, '-t', 'compdb',
                              *(['-x'] if expanded else []), rule]))
    return {item['output']: item for item in entries}


def materialize(source, destination, members, linker, build):
    """Re-create thin archives from their Ninja inputs; never read thin with lld /lib."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as stream:
        magic = stream.read(8)
    if magic == b'!<arch>\n':
        shutil.copy2(source, destination)
    elif magic == b'!<thin>\n':
        if not members:
            raise ValueError(f'Thin archive has no Ninja member list: {source}')
        # A response file avoids the Windows command-line size limit.
        rsp = destination.with_suffix(destination.suffix + '.rsp')
        try:
            rsp.write_text(subprocess.list2cmdline([str(Path(build) / p) for p in members]),
                           encoding='utf-8')
            run([linker, '/lib', '/nologo', '/out:' + str(destination), '@' + str(rsp)], cwd=build)
        finally:
            rsp.unlink(missing_ok=True)
    else:
        raise ValueError(f'Not a supported archive: {source}')
    with destination.open('rb') as stream:
        if stream.read(8) != b'!<arch>\n':
            raise ValueError(f'Librarian did not produce an ordinary archive: {destination}')


def discover(source, build, gn, ninja, env):
    # Never modify upstream BUILD.gn or the original build's args/graph.
    work = source / 'out' / ('sdk-contract-' + uuid.uuid4().hex)
    work.mkdir(parents=True)
    label = '//' + work.relative_to(source).as_posix() + ':consumer'
    (work / 'BUILD.gn').write_text('executable("consumer") {\n'
                                  '  sources = [ "probe.cc" ]\n  deps = [ "//base" ]\n}\n')
    (work / 'probe.cc').write_text('int main() { return 0; }\n')
    meta = work / 'meta'
    meta.mkdir()
    shutil.copy2(build / 'args.gn', meta / 'args.gn')
    print('Generating GN consumer metadata...', flush=True)
    run([gn, 'gen', meta, '--root-target=' + label, '--root-pattern=' + label,
         '--ide=json', '--fail-on-unused-args'], cwd=source, env=env)
    target = json.loads((meta / 'project.json').read_text())['targets'][label]
    raw = compdb(ninja, meta, 'link')['consumer.exe']
    expanded = compdb(ninja, meta, 'link', True)['consumer.exe']
    contract = link_contract(expanded_command(raw['command'], expanded['command']), [raw['file']])
    return meta, target, contract


def package_config(stage, includes, flags, defines, contract, inputs, compiler_hash, linker_hash):
    directory = stage / 'lib/cmake/ChromiumBase'
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        '# Generated from the pinned GN consumer contract. Paths are SDK-relative.',
        'include_guard(GLOBAL)',
        'if(NOT WIN32 OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)',
        '  message(FATAL_ERROR "ChromiumBase SDK requires Windows x64")',
        'endif()',
        'if(NOT CMAKE_CXX_COMPILER_ID STREQUAL "Clang" OR NOT MSVC)',
        '  message(FATAL_ERROR "ChromiumBase requires clang-cl and its SDK toolchain file")',
        'endif()',
        'if(NOT CMAKE_BUILD_TYPE STREQUAL "Release" OR CMAKE_CONFIGURATION_TYPES)',
        '  message(FATAL_ERROR "This SDK supports single-configuration Release builds")',
        'endif()',
        'file(SHA256 "${CMAKE_CXX_COMPILER}" _cb_compiler_hash)',
        f'if(NOT _cb_compiler_hash STREQUAL "{compiler_hash}")',
        '  message(FATAL_ERROR "Use the exact LLVM compiler used to export this SDK")',
        'endif()',
        'file(SHA256 "${CMAKE_LINKER}" _cb_linker_hash)',
        f'if(NOT _cb_linker_hash STREQUAL "{linker_hash}")',
        '  message(FATAL_ERROR "Use the exact LLVM linker used to export this SDK")',
        'endif()',
        'if(NOT CMAKE_MSVC_RUNTIME_LIBRARY STREQUAL "MultiThreaded")',
        '  message(FATAL_ERROR "ChromiumBase SDK requires the static Release CRT (/MT)")',
        'endif()',
        'get_filename_component(_cb_root "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)',
        'add_library(ChromiumBase::base INTERFACE IMPORTED GLOBAL)',
        '# Preserve GN -I precedence: libc++ wrappers must precede Clang/SDK C headers.',
        'set_property(TARGET ChromiumBase::base PROPERTY SYSTEM FALSE)',
    ]
    def prop(name, values, paths=False):
        lines.append(f'set_property(TARGET ChromiumBase::base PROPERTY {name}')
        for value in values:
            quoted = cmake_quote(value)
            if paths:
                quoted = '"${_cb_root}/' + quoted[1:]
            lines.append('  ' + quoted)
        lines.append(')')
    prop('INTERFACE_INCLUDE_DIRECTORIES', includes, True)
    prop('INTERFACE_COMPILE_OPTIONS', flags)
    prop('INTERFACE_COMPILE_DEFINITIONS', defines)
    prop('INTERFACE_LINK_OPTIONS', list(dict.fromkeys(contract['options'])))
    prop('INTERFACE_LINK_LIBRARIES', inputs, True)
    lines.append('set_property(TARGET ChromiumBase::base APPEND PROPERTY INTERFACE_LINK_LIBRARIES')
    lines.extend('  ' + cmake_quote(lib) for lib in contract['system_libs'])
    lines += [')', 'unset(_cb_root)', 'unset(_cb_compiler_hash)', 'unset(_cb_linker_hash)', '']
    (directory / 'ChromiumBaseConfig.cmake').write_text('\n'.join(lines), encoding='utf-8')
    for name in ('chromium-base-toolchain.cmake', 'chromium-base-rules.cmake'):
        shutil.copy2(ROOT / 'cmake' / name, directory / name)


def export(args):
    source, build, dest = (Path(p).resolve() for p in (args.source, args.build_dir, args.destination))
    contained(build, source / 'out')
    args_text = (build / 'args.gn').read_text(encoding='utf-8')
    settings = parse_args(args_text)
    validate_configuration(settings)
    llvm = Path(settings['clang_base_path']).resolve()
    check_destination(dest, [source, llvm, ROOT / '.tools'])
    # Managed builds must already have a successful build manifest. The older audited
    # build may be exported only through the explicit --allow-unmanaged-build switch.
    manifest = build / '.chromium-base.json'
    if not manifest.exists() and not args.allow_unmanaged_build:
        raise ValueError('Build is unmanaged; use the driver or explicitly allow this existing build')
    print('Verifying source snapshot integrity...', flush=True)
    identity = verify_snapshot(source)
    if manifest.exists():
        record = json.loads(manifest.read_text())
        if record.get('state') != 'built':
            raise ValueError('Managed build must be successfully built before export')
        if record.get('identity', {}).get('ninja_path') is None:
            raise ValueError('SDK export requires a build configured with direct Ninja (--ninja), not autoninja')
        # The build driver validates the full manifest; do not weaken its ownership checks.
        from chromium_base import make_plan, read_manifest
        plan = make_plan(source, args.toolchain,
                         str(llvm) if args.toolchain == 'external' else None)
        if Path(plan['output']).resolve() != build:
            raise ValueError('Build path does not match selected toolchain')
        # read_manifest also needs the original environment identity.
        from chromium_base import inspect_environment
        report = inspect_environment(plan, gn=args.gn, ninja=args.ninja)
        read_manifest(plan, report)
    elif args.toolchain == 'chromium' and llvm != (ROOT / '.tools/chromium-llvm').resolve():
        raise ValueError('Selected Chromium LLVM does not match build arguments')
    clang, linker = llvm / 'bin/clang-cl.exe', llvm / 'bin/lld-link.exe'
    from chromium_base import verify_generated_toolchain
    verify_generated_toolchain({'source': str(source), 'output': str(build), 'llvm_root': str(llvm)})
    env = dict(os.environ, DEPOT_TOOLS_WIN_TOOLCHAIN='0', CHROMIUM_BASE_PYTHON=sys.executable,
               PYTHONDONTWRITEBYTECODE='1')
    print('Checking/building base dependencies...', flush=True)
    run([args.ninja, '-C', build, '-j', str(args.jobs), 'base'], env=env)
    if (build / 'args.gn').read_text(encoding='utf-8') != args_text:
        raise ValueError('Build arguments changed during export')
    meta, target, contract = discover(source, build, args.gn, args.ninja, env)
    if (meta / contract['linker']).resolve() != linker:
        raise ValueError('GN consumer selected a different linker')
    raw_ar = compdb(args.ninja, build, 'alink')
    full_ar = compdb(args.ninja, build, 'alink', True)
    flags, extra_includes = consumer_flags(target['cflags'] + target['cflags_cc'])
    defines = [d for d in target['defines'] if d != 'USE_LIBCXX_MODULES']
    if any(d.startswith(('BASE_IMPLEMENTATION', 'IS_RAW_PTR_IMPL')) for d in defines):
        raise ValueError('Implementation defines leaked into consumer configuration')
    include_paths = []
    for value in target['include_dirs']:
        if not value.startswith('//'):
            raise ValueError('Unexpected GN include path: ' + value)
        include_paths.append(source / value[2:])
    include_paths += [meta / p for p in extra_includes]
    includes = []
    for path in include_paths:
        path = path.resolve()
        if path.is_relative_to(meta / 'gen'):
            relative = 'include/generated/' + path.relative_to(meta / 'gen').as_posix()
        else:
            contained(path, source)
            if path.is_relative_to(source / 'out'):
                raise ValueError('Unexpected build-local include path: ' + str(path))
            relative = 'include/source/' + path.relative_to(source).as_posix()
        includes.append(relative.rstrip('/.'))
    dest.parent.mkdir(parents=True, exist_ok=True)
    # A unique sibling staging directory is kept on failure for diagnosis, never published.
    stage = Path(tempfile.mkdtemp(prefix=dest.name + '.staging-', dir=dest.parent))
    print('Staging SDK:', stage, flush=True)
    inventory = json.loads((source / INVENTORY).read_text())
    for name in inventory['files']:
        src = source / name
        if is_header(name):
            target_file = stage / 'include/source' / name
        elif (src.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'AUTHORS')) or
              src.name == 'README.chromium'):
            target_file = stage / 'licenses/source' / name
        else:
            continue
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target_file)
    for src in regular_files(build / 'gen'):
        name = src.relative_to(build / 'gen').as_posix()
        if is_header(name):
            target_file = stage / 'include/generated' / name
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target_file)
    inputs, artifacts = [], []
    for index, value in enumerate(contract['inputs']):
        path = (build / value).resolve()
        if path.is_relative_to(build):
            relative = path.relative_to(build)
        elif path.is_relative_to(llvm):
            relative = Path('compiler-runtime') / path.relative_to(llvm)
        else:
            raise ValueError('Runtime input outside build/compiler: ' + value)
        if not path.is_file():
            raise ValueError('Missing runtime input: ' + str(path))
        output = stage / 'lib' / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in ('.lib', '.rlib'):
            members = None
            key = path.relative_to(build).as_posix() if path.is_relative_to(build) else ''
            if key in raw_ar:
                ar_contract = link_contract(expanded_command(raw_ar[key]['command'],
                                                           full_ar[key]['command']), [])
                if (build / ar_contract['linker']).resolve() != linker:
                    raise ValueError('Archive uses a different linker')
                members = ar_contract['inputs']
                for member in members:
                    contained(build / member, build)
            materialize(path, output, members, linker, build)
        else:
            shutil.copy2(path, output)
        name = output.relative_to(stage).as_posix()
        inputs.append(name)
        artifacts.append(dict(path=name, source_sha256=sha256(path), sha256=sha256(output)))
        if (index + 1) % 100 == 0:
            print(f'Packaged {index + 1}/{len(contract["inputs"])} link inputs', flush=True)
    for relative in includes:
        if not (stage / relative).is_dir():
            raise ValueError('Exported include directory missing: ' + relative)
    compiler_hash = sha256(clang)
    package_config(stage, includes, flags, defines, contract, inputs, compiler_hash, sha256(linker))
    # Keep pinned compiler/Rust licenses with the source dependency licenses.
    for name, root in [('llvm', llvm), ('rust', Path(settings['rust_sysroot_absolute']))]:
        for item in regular_files(root):
            if item.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):
                output = stage / 'licenses' / name / item.relative_to(root)
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, output)
    provenance = dict(schema=1, source=identity, toolchain=args.toolchain,
                      configuration='windows-x64-static-release',
                      compiler_version=run([clang, '--version']).strip(), compiler_sha256=compiler_hash,
                      linker_sha256=sha256(linker), gn_args=args_text, artifacts=artifacts,
                      source_lock=inventory['lock'], includes=includes, defines=defines,
                      compile_options=flags, link_options=contract['options'],
                      system_libraries=contract['system_libs'])
    (stage / 'sdk-manifest.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    (stage / 'files.sha256.json').write_text(json.dumps({
        p.relative_to(stage).as_posix(): sha256(p) for p in regular_files(stage)
    }, indent=2), encoding='utf-8')
    check_destination(dest, [source, llvm, ROOT / '.tools'])
    stage.rename(dest)
    print(f'Exported {len(inputs)} runtime inputs to {dest}', flush=True)
    return dest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=str(ROOT / 'vendor/chromium'))
    parser.add_argument('--build-dir', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--toolchain', choices=['chromium', 'external'], required=True)
    parser.add_argument('--gn', default=str(ROOT / '.tools/gn/gn.exe'))
    parser.add_argument('--ninja', default=str(ROOT / '.tools/ninja/ninja.exe'))
    parser.add_argument('--jobs', type=int, default=6)
    parser.add_argument('--allow-unmanaged-build', action='store_true')
    try:
        export(parser.parse_args())
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print('SDK export failed:', error, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
