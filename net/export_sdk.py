#!/usr/bin/env python3
"""Export a Windows x64 Release component build of //net as a CMake SDK."""

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'base/scripts'))

from base.scripts import export_sdk as base_export
from chromium_base import build_environment, verify_generated_toolchain
from sdk_metadata import consumer_flags, expanded_command, link_contract, parse_args, runtime_contract
from sync_source import INVENTORY, regular_files, sha256, verify_snapshot


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def include_directory(path, source, build):
    path = path.resolve()
    if path.is_relative_to(build / 'gen'):
        return (Path('include/generated') / path.relative_to(build / 'gen')).as_posix()
    if path.is_relative_to(source / 'out') or not path.is_relative_to(source):
        raise ValueError(f'Unsupported GN include directory: {path}')
    return (Path('include/source') / path.relative_to(source)).as_posix()


def build_libraries(ninja, build):
    outputs = base_export.run([ninja, '-C', build, '-t', 'targets', 'all'])
    return [name for entry in outputs.splitlines() if (name := entry.rpartition(': ')[0]).lower().endswith('.lib')]


def get_contract(component, target, raw, expanded, source, build, libraries):
    program = f'{component}_consumer.exe'
    flags, extra = consumer_flags(target['cflags'] + target['cflags_cc'])
    defines = [value for value in target['defines'] if value != 'USE_LIBCXX_MODULES']
    runtime_contract(flags, defines, 'shared')
    if any(d.split('=', 1)[0] in ('NET_IMPLEMENTATION', 'BASE_IMPLEMENTATION', 'IS_RAW_PTR_IMPL')
           for d in defines):
        raise ValueError('Implementation definitions in the consumer contract')
    includes = []
    for entry in target['include_dirs']:
        if not entry.startswith('//'):
            raise ValueError(f'Unsupported GN include directory: {entry}')
        includes.append(include_directory(source / entry[2:], source, build))
    includes.extend(include_directory(build / p, source, build) for p in extra)
    entry = raw[program]
    link = link_contract(expanded_command(entry['command'], expanded[program]['command']),
                         [entry['file']], libraries)
    return dict(flags=flags, defines=defines, includes=list(dict.fromkeys(includes)), link=link)


def runtime_inputs(build, component):
    """GN runtime entries are relative to the executable and preserve data directories."""
    program = f'{component}_consumer'
    result = {}
    for entry in (build / f'{program}.runtime_deps').read_text(encoding='utf-8').splitlines():
        path = base_export.contained(build / entry, build)
        if path == build / (program + '.exe') or path.suffix.lower() == '.pdb':
            continue
        files = regular_files(path) if path.is_dir() else [path]
        for item in files:
            if not item.is_file():
                raise FileNotFoundError(f'Missing GN runtime dependency: {item}')
            result['bin/' + item.relative_to(build).as_posix()] = item
    if f'bin/{component}.dll' not in result:
        raise ValueError(f'Missing {component}.dll in GN component runtime list')
    return result


def link_inputs(build, llvm, contract):
    result = {}
    for entry in contract['link']['inputs']:
        path = (build / entry).resolve()
        if path.is_relative_to(build):
            name = 'lib/' + path.relative_to(build).as_posix()
        elif path.is_relative_to(llvm):
            name = 'lib/compiler-runtime/' + path.relative_to(llvm).as_posix()
        else:
            raise ValueError(f'Link input outside the build and toolchain: {path}')
        if not path.is_file():
            raise FileNotFoundError(f'Missing GN link input: {path}')
        result[name] = path
    return result


def stage_inputs(stage, inputs, linker, build, ninja):
    archives = None
    for name, path in inputs.items():
        if not name.startswith('lib/') or path.suffix.lower() not in ('.lib', '.rlib'):
            copy_file(path, stage / name)
            continue
        with path.open('rb') as stream:
            thin = stream.read(8) == b'!<thin>\n'
        members = None
        if thin:
            if archives is None:
                archives = [base_export.compdb(ninja, build, 'alink', x) for x in (False, True)]
            key = base_export.contained(path, build).relative_to(build).as_posix()
            raw, expanded = (db[key]['command'] for db in archives)
            archive = link_contract(expanded_command(raw, expanded), [])
            if (build / archive['linker']).resolve() != linker:
                raise ValueError(f'Thin archive uses a different linker: {path}')
            members = [str(base_export.contained(build / member, build)) for member in archive['inputs']]
        base_export.materialize(path, stage / name, members, linker, build)


def check_base_sdk(sdk, revision, compiler, linker, contract, inputs):
    path = sdk / 'sdk-manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if (manifest.get('configuration') != 'windows-x64-shared-release'
            or manifest.get('source', {}).get('revision') != revision
            or manifest.get('compiler_sha256') != compiler or manifest.get('linker_sha256') != linker
            or manifest.get('defines') != contract['defines']
            or manifest.get('compile_options') != contract['flags']):
        raise ValueError('Existing ChromiumBase SDK does not match the GN base consumer ABI')
    recorded = {item['path']: item for item in manifest['artifacts']}
    for name, built in inputs.items():
        item = recorded.get(name)
        if (not item or not (sdk / name).is_file() or item['source_sha256'] != sha256(built)
                or item['sha256'] != sha256(sdk / name)):
            raise ValueError(f'Existing ChromiumBase SDK has a different artifact: {name}')
    if not (sdk / 'lib/cmake/ChromiumBase/ChromiumBaseConfig.cmake').is_file():
        raise ValueError('Missing existing ChromiumBase CMake package')
    return sha256(path)


def write_net_config(stage, contract, inputs, runtime, base_digest):
    directory = stage / 'lib/cmake/ChromiumNet'
    directory.mkdir(parents=True)
    lines = ['include_guard(GLOBAL)', 'include(CMakeFindDependencyMacro)']
    if base_digest:
        lines += ['find_dependency(ChromiumBase CONFIG)',
                  'file(SHA256 "${ChromiumBase_DIR}/../../../sdk-manifest.json" _cn_hash)',
                  f'if(NOT _cn_hash STREQUAL "{base_digest}")',
                  '  message(FATAL_ERROR "ChromiumNet requires the ChromiumBase SDK used for export")',
                  'endif()', 'unset(_cn_hash)']
    else:
        # Reject an already loaded, different base target before the include guard can mask it.
        lines += ['get_filename_component(_cn_base "${CMAKE_CURRENT_LIST_DIR}/../ChromiumBase" REALPATH)',
                  'if(TARGET ChromiumBase::base)',
                  '  get_filename_component(_cn_loaded "${ChromiumBase_DIR}" REALPATH)',
                  '  if(NOT _cn_loaded STREQUAL _cn_base)',
                  '    message(FATAL_ERROR "ChromiumNet requires its bundled ChromiumBase SDK")',
                  '  endif()', 'endif()', 'set(ChromiumBase_DIR "${_cn_base}")',
                  'find_dependency(ChromiumBase CONFIG)', 'unset(_cn_loaded)', 'unset(_cn_base)']
    lines += ['get_filename_component(_cn_root "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)',
              'add_library(ChromiumNet::net INTERFACE IMPORTED GLOBAL)',
              'set_property(TARGET ChromiumNet::net PROPERTY SYSTEM FALSE)']

    def prop(name, values, relative=False):
        lines.append(f'set_property(TARGET ChromiumNet::net PROPERTY {name}')
        for value in values:
            quoted = base_export.cmake_quote(value)
            lines.append('  ' + ('"${_cn_root}/' + quoted[1:] if relative else quoted))
        lines.append(')')

    prop('INTERFACE_INCLUDE_DIRECTORIES', contract['includes'], True)
    prop('INTERFACE_COMPILE_OPTIONS', contract['flags'])
    prop('INTERFACE_COMPILE_DEFINITIONS', contract['defines'])
    prop('INTERFACE_LINK_OPTIONS', dict.fromkeys(contract['link']['options']))
    prop('INTERFACE_LINK_LIBRARIES', inputs, True)
    lines.append('set_property(TARGET ChromiumNet::net APPEND PROPERTY INTERFACE_LINK_LIBRARIES')
    lines += ['  ChromiumBase::base', *('  ' + base_export.cmake_quote(lib)
                                        for lib in contract['link']['system_libs']), ')']
    prop('CHROMIUM_NET_RUNTIME_FILES', runtime, True)
    lines += ['function(chromium_net_deploy_runtime target)',
              '  chromium_base_deploy_runtime("${target}")',
              '  get_target_property(_files ChromiumNet::net CHROMIUM_NET_RUNTIME_FILES)',
              '  foreach(_file IN LISTS _files)',
              '    file(RELATIVE_PATH _relative "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../../../bin" "${_file}")',
              '    get_filename_component(_dir "${_relative}" DIRECTORY)',
              '    add_custom_command(TARGET "${target}" POST_BUILD',
              '      COMMAND "${CMAKE_COMMAND}" -E make_directory "$<TARGET_FILE_DIR:${target}>/${_dir}"',
              '      COMMAND "${CMAKE_COMMAND}" -E copy_if_different "${_file}"',
              '        "$<TARGET_FILE_DIR:${target}>/${_relative}" VERBATIM)',
              '  endforeach()', 'endfunction()', 'unset(_cn_root)', '']
    (directory / 'ChromiumNetConfig.cmake').write_text('\n'.join(lines), encoding='utf-8')


def stage_headers_and_licenses(source, build, stage, settings):
    inventory = json.loads((source / INVENTORY).read_text(encoding='utf-8'))
    for name in inventory['files']:
        path = source / name
        if base_export.is_header(name):
            copy_file(path, stage / 'include/source' / name)
        elif path.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'AUTHORS')) or path.name == 'README.chromium':
            copy_file(path, stage / 'licenses/source' / name)
    for path in regular_files(build / 'gen'):
        name = path.relative_to(build / 'gen').as_posix()
        if base_export.is_header(name):
            copy_file(path, stage / 'include/generated' / name)
    for name, setting in [('llvm', 'clang_base_path'), ('rust', 'rust_sysroot_absolute')]:
        root = Path(settings[setting]).resolve()
        for path in regular_files(root):
            if path.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):
                copy_file(path, stage / 'licenses' / name / path.relative_to(root))


def export(args):
    source = args.source.resolve()
    build = base_export.contained(args.build_dir or source / 'out/sh', source / 'out')
    destination = args.destination.resolve()
    args_text = (build / 'args.gn').read_text(encoding='utf-8')
    settings = parse_args(args_text)
    required = dict(target_cpu='x64', is_component_build=True, is_debug=False, is_clang=True,
                    use_lld=True, use_custom_libcxx=True)
    if settings.get('target_os', 'win') != 'win' or any(settings.get(k) != v for k, v in required.items()):
        raise ValueError('ChromiumNet SDK requires Windows x64 Release component GN arguments')
    llvm = Path(settings['clang_base_path']).resolve()
    protected = [source, llvm, ROOT / '.tools', *([args.base_sdk] if args.base_sdk else [])]
    base_export.check_destination(destination, protected)
    verify_generated_toolchain(dict(output=str(build), source=str(source), llvm_root=str(llvm)))
    print('Verifying source snapshot integrity...', flush=True)
    identity = verify_snapshot(source)
    env = build_environment({})
    gn, ninja = args.gn.resolve(), args.ninja.resolve()
    print('Building base and net consumer probes...', flush=True)
    base_export.run([ninja, '-C', build, '-j', args.jobs, 'base_consumer.exe', 'net_consumer.exe'], env=env)
    targets = json.loads(base_export.run([gn, 'desc', build, '//sdk_probe:*', '--format=json'],
                                         cwd=source, env=env))
    libraries = build_libraries(ninja, build)
    raw, expanded = (base_export.compdb(ninja, build, 'link', x) for x in (False, True))
    compiler_hash, linker_hash = (sha256(llvm / 'bin' / tool) for tool in ('clang-cl.exe', 'lld-link.exe'))
    contracts, links, runtimes = {}, {}, {}
    for component in ('base', 'net'):
        target = targets[f'//sdk_probe:{component}_consumer']
        contract = get_contract(component, target, raw, expanded, source, build, libraries)
        if (build / contract['link']['linker']).resolve() != llvm / 'bin/lld-link.exe':
            raise ValueError('GN consumer selected a different linker')
        contracts[component] = contract
        links[component] = link_inputs(build, llvm, contract)
        runtimes[component] = runtime_inputs(build, component)
    base = contracts['base']
    base_files = links['base'] | runtimes['base']
    base_digest = check_base_sdk(args.base_sdk.resolve(), identity['revision'], compiler_hash, linker_hash,
                                 base, base_files) if args.base_sdk else None
    net_links = {k: v for k, v in links['net'].items() if k not in links['base']}
    net_runtime = {k: v for k, v in runtimes['net'].items() if k not in runtimes['base']}
    for name in ('net.dll.lib', 'base_i18n.dll.lib'):
        if 'lib/' + name not in net_links:
            raise ValueError(f'Missing GN import library in the net SDK probe: {name}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=destination.name + '.stage-', dir=destination.parent) as temp:
        stage = Path(temp) / 'sdk'
        print('Staging headers, libraries and runtime files...', flush=True)
        stage_headers_and_licenses(source, build, stage, settings)
        for contract in contracts.values():
            for name in contract['includes']:
                if not (stage / name).is_dir():
                    raise ValueError('Missing exported include directory: ' + name)
        staged_inputs = net_links | net_runtime
        if not base_digest:
            staged_inputs.update(base_files)
            base_export.package_config(stage, base['includes'], base['flags'], base['defines'], base['link'],
                                       list(links['base']), compiler_hash, linker_hash, linkage='shared',
                                       runtime=list(runtimes['base']))
        stage_inputs(stage, staged_inputs, llvm / 'bin/lld-link.exe', build, ninja)
        write_net_config(stage, contracts['net'], net_links, net_runtime, base_digest)
        if (build / 'args.gn').read_text(encoding='utf-8') != args_text:
            raise ValueError('GN build arguments changed during export')
        net = contracts['net']
        write_json(stage / 'sdk-manifest.json', dict(schema=1, component='net', source=identity,
                   configuration='windows-x64-shared-release', gn_args=args_text,
                   compiler_sha256=compiler_hash, linker_sha256=linker_hash, base_sdk_sha256=base_digest,
                   includes=net['includes'], defines=net['defines'], compile_options=net['flags'],
                   link_options=net['link']['options'], system_libraries=net['link']['system_libs'],
                   link_inputs=[name for name in staged_inputs if name.startswith('lib/')],
                   runtime_files=[name for name in staged_inputs if name.startswith('bin/')]))
        write_json(stage / 'files.sha256.json',
                   {p.relative_to(stage).as_posix(): sha256(p) for p in regular_files(stage)})
        base_export.check_destination(destination, protected)
        stage.rename(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'vendor/chromium-net')
    parser.add_argument('--build-dir', type=Path, help='default: <source>/out/sh')
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--base-sdk', type=Path, help='require and reuse an exact existing ChromiumBase shared SDK')
    parser.add_argument('--gn', type=Path, default=ROOT / '.tools/gn/gn.exe')
    parser.add_argument('--ninja', type=Path, default=ROOT / '.tools/ninja/ninja.exe')
    parser.add_argument('--linkage', choices=['shared'], default='shared')
    parser.add_argument('--jobs', type=int, default=6)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    try:
        print('Exported SDK:', export(args), flush=True)
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print('SDK export failed:', error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
